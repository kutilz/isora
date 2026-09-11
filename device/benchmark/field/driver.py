#!/usr/bin/env python3
"""
Field Driver — otomasi trigger untuk Blok D/E (konteks) & Blok G (reliability)
=============================================================================
Mengirim command/button ke device lewat HTTP dan mencatat tiap aksi + hasilnya
ke marks.jsonl (kind="action") sehingga analyze.py bisa menilai.

Token auth diambil otomatis via GET /auth/token (hanya jalan dari loopback/LAN),
atau kirim --token manual.

Subcommand:

  describe   Trigger 'describe' N kali, ukur latency + cache (Blok D/E).
             python3 .../driver.py D1 describe --n 5 --gap 10
             (operator susun scene + catat ground-truth pakai mark.py phase/note
              sebelum tiap trigger; transcript deskripsi otomatis terekam)

  modeswitch Stress mode-switch N kali via tombol-sim MODE (Blok G).
             python3 .../driver.py G1 modeswitch --n 50 --gap 1.5

  setmode    Set mode eksplisit (explorer|context) via /command set_mode.
             python3 .../driver.py G1 setmode context

  describe1  Sekali describe (mis. untuk uji barge-in / network-drop di Blok G).
             python3 .../driver.py G1 describe1 --label barge
             python3 .../driver.py G1 describe1 --label netdown

  config     Live-tune config (Blok kalibrasi / what-if).
             python3 .../driver.py X config conf_threshold=0.5 detection_min_streak=2
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from _common import (  # noqa: E402
    DEFAULT_BASE, session_dir, append_jsonl, http_get_json, http_post_json,
    fetch_token, now,
)


def _marks_path(session):
    return os.path.join(session_dir(session, create=True), "marks.jsonl")


def _action(session, **fields):
    ts, iso, _ = now()
    rec = {"ts": ts, "iso": iso, "kind": "action", **fields}
    append_jsonl(_marks_path(session), rec)
    return rec


def _scene_last(base):
    st = http_get_json(base, "/status", timeout=4.0) or {}
    sm = st.get("scene_metrics") or {}
    return sm.get("last")


def _wait_scene(base, prev_id, timeout_s=30.0):
    """Tunggu scene_metrics.last.id berubah & terisi (to_audio_ms / source).
    Mengembalikan record scene (dict) atau None bila timeout."""
    deadline = time.monotonic() + timeout_s
    last = None
    while time.monotonic() < deadline:
        last = _scene_last(base)
        if isinstance(last, dict) and last.get("id") != prev_id:
            # tunggu fase audio terisi (cache: to_audio_ms; synth: source+audio)
            if last.get("audio_source") is not None or last.get("to_audio_ms") is not None:
                return last
        time.sleep(0.4)
    return last  # mungkin partial / None


# ─── Subcommands ────────────────────────────────────────────────────────────────

def cmd_describe(session, base, token, n, gap):
    print(f"[driver] describe x{n} (gap {gap}s)", flush=True)
    results = []
    for i in range(n):
        prev = _scene_last(base)
        prev_id = prev.get("id") if isinstance(prev, dict) else None
        t0 = time.monotonic()
        code, resp = http_post_json(base, "/command", {"cmd": "describe"}, token)
        if code != 200:
            print(f"  [{i+1}/{n}] POST /command gagal: {code} {resp}", flush=True)
            _action(session, tag="describe", ok=False, http=code, idx=i)
            continue
        scene = _wait_scene(base, prev_id, timeout_s=40.0)
        wall = time.monotonic() - t0
        rec = {
            "tag": "describe", "ok": scene is not None, "idx": i,
            "wall_s": round(wall, 2),
        }
        if isinstance(scene, dict):
            rec.update({
                "scene_id": scene.get("id"),
                "text": scene.get("text"),
                "gemini_ms": scene.get("gemini_ms"),
                "source": scene.get("audio_source"),
                "to_audio_ms": scene.get("to_audio_ms"),
                "words": scene.get("words"),
                "cached_words": scene.get("cached_words"),
                "verbosity": scene.get("verbosity"),
            })
            print(f"  [{i+1}/{n}] {scene.get('audio_source')} "
                  f"gemini={scene.get('gemini_ms')}ms to_audio={scene.get('to_audio_ms')}ms "
                  f"\"{(scene.get('text') or '')[:50]}\"", flush=True)
        else:
            print(f"  [{i+1}/{n}] timeout menunggu scene_metrics", flush=True)
        _action(session, **rec)
        results.append(rec)
        if i < n - 1:
            time.sleep(gap)
    ok = sum(1 for r in results if r.get("ok"))
    print(f"[driver] describe selesai: {ok}/{n} sukses", flush=True)


def cmd_modeswitch(session, base, token, n, gap):
    print(f"[driver] mode-switch stress x{n} (gap {gap}s)", flush=True)
    ok = 0
    for i in range(n):
        st_before = http_get_json(base, "/status", timeout=4.0) or {}
        mode_before = st_before.get("mode")
        code, resp = http_post_json(base, "/button", {"button": "mode"}, token)
        # /button tidak butuh auth, tapi token tetap aman dikirim
        time.sleep(min(gap, 1.5))
        st_after = http_get_json(base, "/status", timeout=4.0) or {}
        mode_after = st_after.get("mode")
        changed = (mode_after is not None and mode_after != mode_before)
        ok += 1 if changed else 0
        _action(session, tag="modeswitch", idx=i, http=code,
                mode_before=mode_before, mode_after=mode_after, changed=changed)
        if (i + 1) % 10 == 0:
            print(f"  {i+1}/{n}  ({mode_before}->{mode_after})  ok={ok}", flush=True)
        rem = gap - min(gap, 1.5)
        if rem > 0:
            time.sleep(rem)
    print(f"[driver] mode-switch selesai: {ok}/{n} berubah, "
          f"device {'HIDUP' if http_get_json(base, '/status') else 'TIDAK MERESPON'}",
          flush=True)


def cmd_setmode(session, base, token, mode):
    code, resp = http_post_json(base, "/command",
                                {"cmd": "set_mode", "mode": mode}, token)
    _action(session, tag="setmode", mode=mode, http=code)
    time.sleep(1.0)
    st = http_get_json(base, "/status") or {}
    print(f"[driver] setmode {mode} -> http={code} mode_now={st.get('mode')}",
          flush=True)


def cmd_describe1(session, base, token, label):
    """Sekali describe, dipakai untuk Blok G (barge-in / network-drop). Caption
    hasil/cue terekam oleh recorder; di sini kita catat aksi + scene (kalau ada)."""
    prev = _scene_last(base)
    prev_id = prev.get("id") if isinstance(prev, dict) else None
    code, resp = http_post_json(base, "/command", {"cmd": "describe"}, token)
    rec = {"tag": "describe1", "label": label, "http": code}
    print(f"[driver] describe1 ({label}) http={code}", flush=True)
    scene = _wait_scene(base, prev_id, timeout_s=20.0)
    if isinstance(scene, dict):
        rec.update({"scene_id": scene.get("id"), "source": scene.get("audio_source"),
                    "text": scene.get("text")})
    _action(session, **rec)


def cmd_config(session, base, token, pairs):
    payload = {}
    for p in pairs:
        if "=" not in p:
            continue
        k, v = p.split("=", 1)
        # coerce angka/bool sederhana
        if v.lower() in ("true", "false"):
            payload[k] = (v.lower() == "true")
        else:
            try:
                payload[k] = int(v)
            except ValueError:
                try:
                    payload[k] = float(v)
                except ValueError:
                    payload[k] = v
    code, resp = http_post_json(base, "/config", payload, token)
    _action(session, tag="config", payload=payload, http=code)
    print(f"[driver] config {payload} -> http={code} {resp}", flush=True)


def main():
    ap = argparse.ArgumentParser(description="I-Sora field driver")
    ap.add_argument("session")
    ap.add_argument("command", choices=["describe", "modeswitch", "setmode",
                                        "describe1", "config"])
    ap.add_argument("extra", nargs="*", help="argumen untuk setmode/config")
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--token", default="")
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--gap", type=float, default=8.0)
    ap.add_argument("--label", default="describe1")
    args = ap.parse_args()

    token = args.token or fetch_token(args.base)
    if not token:
        print("[driver] WARNING: tidak ada token (POST /command bisa 401). "
              "Jalankan di device/LAN, atau beri --token.", flush=True)

    if args.command == "describe":
        cmd_describe(args.session, args.base, token, args.n, args.gap)
    elif args.command == "modeswitch":
        cmd_modeswitch(args.session, args.base, token, args.n, args.gap)
    elif args.command == "setmode":
        cmd_setmode(args.session, args.base, token,
                    args.extra[0] if args.extra else "explorer")
    elif args.command == "describe1":
        cmd_describe1(args.session, args.base, token, args.label)
    elif args.command == "config":
        cmd_config(args.session, args.base, token, args.extra)


if __name__ == "__main__":
    main()

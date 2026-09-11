#!/usr/bin/env python3
"""
Field Recorder — rekam stream status device ke events.jsonl
===========================================================
Poll `GET /status` pada laju tetap dan simpan tiap sample (detections, latency,
caption, scene_metrics, suhu) ke `<session>/events.jsonl`. Tidak menyentuh
kamera/NPU — murni pembaca HTTP, jadi aman jalan berdampingan dgn app utama.

CATATAN OVERHEAD (penting untuk akurasi):
  `get_status()` di device melakukan subprocess (iwgetid/iw) tiap panggilan.
  Pada device 1-core, polling laju tinggi membebani CPU dan dapat MENGGANGGU
  ukuran latency/FPS. Maka:
    • Konten (recall/posisi/tier/false-positive) → pakai --hz 2..3 (aman).
    • Latency presisi (time-to-announce) → idealnya pakai in-process tracer
      (lihat tracer.py); sebagai fallback boleh --hz 8..10 TAPI hanya untuk
      window pendek dan sadar ada beban ekstra.

Pemakaian (jalankan di device via SSH supaya satu jam dgn mark/driver):
  python3 device/benchmark/field/recorder.py --session A1 --hz 3
  python3 device/benchmark/field/recorder.py --session A1 --hz 8 --duration 120
  python3 device/benchmark/field/recorder.py --session A1 --snapshots 0.5   # simpan jpeg 0.5/s

Stop: Ctrl-C, atau buat file stop: touch /tmp/isora_field_stop
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from _common import (  # noqa: E402
    DEFAULT_BASE, session_dir, append_jsonl, http_get_json, http_get,
    now, compact_det,
)

STOP_FILE = "/tmp/isora_field_stop"


def _scene_brief(status: dict) -> dict:
    """Ambil ringkas scene_metrics.last (deskripsi terakhir + timing) dari status."""
    sm = status.get("scene_metrics") or {}
    last = sm.get("last")
    summ = sm.get("summary") or {}
    out = {"hit_rate": summ.get("hit_rate"), "count": summ.get("count")}
    if isinstance(last, dict):
        out.update({
            "id":        last.get("id"),
            "text":      last.get("text"),
            "gemini_ms": last.get("gemini_ms"),
            "source":    last.get("audio_source"),
            "to_audio_ms": last.get("to_audio_ms"),
            "words":     last.get("words"),
            "cached":    last.get("cached_words"),
        })
    return out


def run(session: str, base: str, hz: float, duration: float, snapshots: float):
    sdir = session_dir(session, create=True)
    events_path = os.path.join(sdir, "events.jsonl")
    snaps_dir = os.path.join(sdir, "snapshots")

    interval = 1.0 / hz if hz > 0 else 0.33
    snap_interval = (1.0 / snapshots) if snapshots and snapshots > 0 else 0.0
    if snap_interval:
        os.makedirs(snaps_dir, exist_ok=True)

    # bersihkan stop-file lama
    try:
        os.remove(STOP_FILE)
    except FileNotFoundError:
        pass

    print(f"[recorder] session={session} base={base} hz={hz} "
          f"dur={'∞' if not duration else duration}s -> {events_path}", flush=True)

    # marker awal sesi (memudahkan analyze menandai mulai)
    ts0, iso0, mono0 = now()
    append_jsonl(events_path, {
        "ts": ts0, "iso": iso0, "kind": "recorder_start", "hz": hz,
    })

    n = 0
    last_snap = 0.0
    start = time.monotonic()
    try:
        while True:
            if os.path.exists(STOP_FILE):
                print("[recorder] stop-file terdeteksi — berhenti", flush=True)
                break
            if duration and (time.monotonic() - start) >= duration:
                break

            loop_t0 = time.monotonic()
            ts, iso, mono = now()
            status = http_get_json(base, "/status", timeout=4.0)

            if status is None:
                # device tak merespon — catat sebagai gap (berguna utk deteksi crash)
                append_jsonl(events_path, {
                    "ts": ts, "iso": iso, "kind": "status_fail",
                })
            else:
                dets = [compact_det(d) for d in (status.get("detections") or [])]
                lat = status.get("latency") or {}
                cap = status.get("last_caption") or {}
                rec = {
                    "ts": ts, "iso": iso, "kind": "sample",
                    "mode": status.get("mode"),
                    "fps": lat.get("fps"),
                    "infer_ms": lat.get("inference_ms"),
                    "total_ms": lat.get("total_ms"),
                    "temp": status.get("temperature"),
                    "battery": status.get("battery"),
                    "dets": dets,
                    "caption": {
                        "text": cap.get("text", ""),
                        "iso": cap.get("time_iso", ""),
                        "priority": cap.get("priority", "low"),
                    },
                    "scene": _scene_brief(status),
                }
                append_jsonl(events_path, rec)
                n += 1

            # snapshot opsional (rendah laju — JPEG encode membebani device)
            if snap_interval and (mono - last_snap) >= snap_interval:
                last_snap = mono
                code, body = http_get(base, "/snapshot", timeout=4.0)
                if code == 200 and body:
                    fn = os.path.join(snaps_dir, f"{ts:.3f}.jpg")
                    try:
                        with open(fn, "wb") as f:
                            f.write(body)
                    except OSError:
                        pass

            # progress ringan ke konsol
            if n and n % max(1, int(hz * 10)) == 0:
                print(f"[recorder] {n} samples...", flush=True)

            sleep_left = interval - (time.monotonic() - loop_t0)
            if sleep_left > 0:
                time.sleep(sleep_left)
    except KeyboardInterrupt:
        print("\n[recorder] Ctrl-C — berhenti", flush=True)

    ts1, iso1, _ = now()
    append_jsonl(events_path, {"ts": ts1, "iso": iso1, "kind": "recorder_stop",
                               "samples": n})
    print(f"[recorder] selesai — {n} samples ditulis ke {events_path}", flush=True)


def main():
    ap = argparse.ArgumentParser(description="I-Sora field recorder")
    ap.add_argument("--session", required=True, help="nama sesi (folder hasil)")
    ap.add_argument("--base", default=DEFAULT_BASE, help="base URL device")
    ap.add_argument("--hz", type=float, default=3.0, help="laju poll /status")
    ap.add_argument("--duration", type=float, default=0.0,
                    help="durasi detik (0 = sampai Ctrl-C/stop-file)")
    ap.add_argument("--snapshots", type=float, default=0.0,
                    help="laju simpan JPEG /detik (0 = off)")
    args = ap.parse_args()
    run(args.session, args.base, args.hz, args.duration, args.snapshots)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Field Analyze — hitung metrik in-situ dari events.jsonl + marks.jsonl (+ rubrik)
==============================================================================
Mengolah hasil rekaman lab jadi laporan akurasi & reliability per blok:

  Blok A  Explorer: recall, time-to-announce, akurasi posisi & tier
  Blok B  Explorer: phantom (kosong/lensa tertutup), perilaku re-announce, flapping
  Blok D  Konteks : akurasi & kegunaan deskripsi (dari context_rubric.csv operator)
  Blok E  Konteks : latency & cache hit-rate (dari aksi describe driver)
  Blok G  Reliability: mode-switch, barge-in, network-drop, recovery, crash/thermal

Pakai:
  python3 device/benchmark/field/analyze.py --session A1
  python3 device/benchmark/field/analyze.py --dir /path/ke/sesi      # folder eksplisit
  python3 device/benchmark/field/analyze.py --session A1 --json      # cetak JSON saja

Murni stdlib — bisa jalan di device atau di laptop operator.
"""

import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from _common import (  # noqa: E402
    session_dir, read_jsonl, parse_caption, horiz_pos, pct, mean,
)

# ─── Target (di-ground ke config.py + rencana benchmark) ─────────────────────────
CRITICAL_LABELS = {"person", "car", "motorcycle", "bus", "truck", "bicycle"}
SMALL_LABELS    = {"bottle", "handbag", "backpack", "cat"}

T = {
    "A_recall_critical": 0.95, "A_recall_general": 0.90, "A_recall_small": 0.70,
    "A_ttann_detect_median_ms": 800, "A_ttann_detect_p95_ms": 1500,
    "A_pos_acc": 0.90, "A_tier_acc": 0.85,
    "B_phantom_per_5min": 1.0, "B_cover_zero": 0,
    "B_remind_s": 3.0, "B_remind_tol_s": 1.0,
    "D_key_recall": 0.80, "D_pos": 0.80, "D_halluc_max": 0.10, "D_useful": 4.0,
    "E_warm_to_audio_ms": 1500, "E_cold_ms": 9000, "E_hit_rate": 0.70,
    "G_modeswitch_ok": 1.0,
    "thermal_max_c": 80.0, "fps_floor": 15.0,
}

ANN_GRACE_S = 2.0   # toleransi: announcement boleh muncul s/d ini setelah segmen tutup


# ─── Loaders ────────────────────────────────────────────────────────────────────

def load_session(sdir):
    events = read_jsonl(os.path.join(sdir, "events.jsonl"))
    marks  = read_jsonl(os.path.join(sdir, "marks.jsonl"))
    samples = [e for e in events if e.get("kind") == "sample"]
    samples.sort(key=lambda e: e.get("ts", 0))
    marks.sort(key=lambda m: m.get("ts", 0))
    return events, samples, marks


def label_class(lbl):
    if lbl in CRITICAL_LABELS:
        return "critical"
    if lbl in SMALL_LABELS:
        return "small"
    return "general"


# ─── Series derivation ──────────────────────────────────────────────────────────

def extract_announcements(samples):
    """Nav announcements (priority critical/high, ada objek). Dideteksi saat
    (caption.text, caption.iso) berubah → kejadian announce baru."""
    anns = []
    prev_key = None
    for e in samples:
        cap = e.get("caption") or {}
        text = cap.get("text") or ""
        iso = cap.get("iso") or ""
        prio = cap.get("priority") or "low"
        if not text:
            continue
        key = (text, iso)
        if key != prev_key:
            p = parse_caption(text)
            anns.append({"ts": e["ts"], "text": text, "prio": prio, **p})
            prev_key = key
    return anns


def nav_announcements(anns):
    return [a for a in anns if a.get("label") and a.get("prio") in ("critical", "high")]


def first_detect_ts(samples, label, t0, t1):
    for e in samples:
        if e["ts"] < t0 or e["ts"] > t1:
            continue
        for d in e.get("dets") or []:
            if d.get("label") == label:
                return e["ts"]
    return None


def samples_between(samples, t0, t1):
    return [e for e in samples if t0 <= e["ts"] <= t1]


# ─── Blok A ───────────────────────────────────────────────────────────────────

def build_segments(marks, session_end):
    """enter/move/static -> segmen [ts, end] dgn (label,pos,tier). exit menutup
    track aktif untuk label tsb."""
    segs = []
    open_idx = {}   # label -> index segmen yang masih terbuka
    for m in marks:
        tag = m.get("tag")
        ts = m.get("ts")
        if tag in ("enter", "move", "static"):
            lbl = m.get("label")
            # tutup segmen sebelumnya utk label ini di ts sekarang
            if lbl in open_idx:
                segs[open_idx[lbl]]["end"] = ts
            seg = {"label": lbl, "pos": m.get("pos", "tengah"),
                   "tier": m.get("tier"), "dist_m": m.get("dist_m"),
                   "kind": tag, "start": ts, "end": None}
            segs.append(seg)
            open_idx[lbl] = len(segs) - 1
        elif tag == "exit":
            lbl = m.get("label")
            if lbl in open_idx:
                segs[open_idx[lbl]]["end"] = ts
                del open_idx[lbl]
    # tutup segmen yg masih terbuka di akhir sesi
    for lbl, i in open_idx.items():
        if segs[i]["end"] is None:
            segs[i]["end"] = session_end
    return segs


def block_a(samples, marks, navs, session_end):
    segs = build_segments(marks, session_end)
    segs = [s for s in segs if s["kind"] in ("enter", "move") and s["end"]]
    if not segs:
        return {"skipped": True, "reason": "tidak ada mark enter/move"}

    per = []
    for s in segs:
        lbl, pos_exp, tier_exp = s["label"], s["pos"], s["tier"]
        t0, t1 = s["start"], s["end"]
        seg_samples = samples_between(samples, t0, t1)
        present = [e for e in seg_samples
                   if any(d.get("label") == lbl for d in (e.get("dets") or []))]
        detected = len(present) > 0
        det_ts = present[0]["ts"] if present else None

        # announcement pertama utk label ini dalam [t0, t1+grace]
        ann = next((a for a in navs
                    if a["label"] == lbl and t0 <= a["ts"] <= t1 + ANN_GRACE_S), None)
        ttann_mark = (ann["ts"] - t0) * 1000 if ann else None
        ttann_det = ((ann["ts"] - det_ts) * 1000
                     if (ann and det_ts is not None and ann["ts"] >= det_ts) else None)

        # akurasi posisi & tier dari STREAM deteksi (robust, tak tergantung frasa)
        det_pos = [horiz_pos(d.get("pos"))
                   for e in present for d in e.get("dets") or []
                   if d.get("label") == lbl]
        det_tier = [d.get("tier", "far")
                    for e in present for d in e.get("dets") or []
                    if d.get("label") == lbl]
        pos_major = _majority(det_pos)
        tier_major = _majority(det_tier)
        pos_ok = (pos_major == pos_exp) if (detected and pos_exp) else None
        tier_ok = (tier_major == tier_exp) if (detected and tier_exp) else None

        per.append({
            "label": lbl, "class": label_class(lbl), "pos_exp": pos_exp,
            "tier_exp": tier_exp, "dur_s": round(t1 - t0, 1),
            "detected": detected, "announced": ann is not None,
            "ttann_from_detect_ms": _r(ttann_det), "ttann_from_mark_ms": _r(ttann_mark),
            "pos_major": pos_major, "pos_ok": pos_ok,
            "tier_major": tier_major, "tier_ok": tier_ok,
        })

    def recall_for(cls):
        xs = [p for p in per if p["class"] == cls]
        return (sum(1 for p in xs if p["detected"]) / len(xs)) if xs else None

    ttann = [p["ttann_from_detect_ms"] for p in per if p["ttann_from_detect_ms"] is not None]
    pos_ok = [p["pos_ok"] for p in per if p["pos_ok"] is not None]
    tier_ok = [p["tier_ok"] for p in per if p["tier_ok"] is not None]

    res = {
        "segments": len(per),
        "recall_critical": recall_for("critical"),
        "recall_general": recall_for("general"),
        "recall_small": recall_for("small"),
        "announce_rate": (sum(1 for p in per if p["announced"]) / len(per)) if per else None,
        "ttann_detect_median_ms": _r(pct(ttann, 0.5)),
        "ttann_detect_p95_ms": _r(pct(ttann, 0.95)),
        "pos_acc": (sum(pos_ok) / len(pos_ok)) if pos_ok else None,
        "tier_acc": (sum(tier_ok) / len(tier_ok)) if tier_ok else None,
        "per_segment": per,
    }
    res["checks"] = [
        _chk("recall critical", res["recall_critical"], ">=", T["A_recall_critical"], pctfmt=True),
        _chk("recall general", res["recall_general"], ">=", T["A_recall_general"], pctfmt=True),
        _chk("recall small", res["recall_small"], ">=", T["A_recall_small"], pctfmt=True),
        _chk("time-to-announce median (ms)", res["ttann_detect_median_ms"], "<=", T["A_ttann_detect_median_ms"]),
        _chk("time-to-announce p95 (ms)", res["ttann_detect_p95_ms"], "<=", T["A_ttann_detect_p95_ms"]),
        _chk("akurasi posisi", res["pos_acc"], ">=", T["A_pos_acc"], pctfmt=True),
        _chk("akurasi tier", res["tier_acc"], ">=", T["A_tier_acc"], pctfmt=True),
    ]
    return res


# ─── Blok B ───────────────────────────────────────────────────────────────────

def _windows(marks, start_tag, end_tag):
    wins, open_ts = [], None
    for m in marks:
        if m.get("tag") == start_tag:
            open_ts = m.get("ts")
        elif m.get("tag") == end_tag and open_ts is not None:
            wins.append((open_ts, m.get("ts")))
            open_ts = None
    return wins


def block_b(samples, marks, navs, session_end):
    res = {}

    # 1) Phantom saat scene kosong
    empty_wins = _windows(marks, "empty_start", "empty_end")
    empty_min = sum((b - a) for a, b in empty_wins) / 60.0
    empty_phantom = sum(1 for a in navs for (t0, t1) in empty_wins if t0 <= a["ts"] <= t1)
    res["empty_windows"] = len(empty_wins)
    res["empty_minutes"] = round(empty_min, 2)
    res["empty_phantom"] = empty_phantom
    res["phantom_per_5min"] = round(empty_phantom / empty_min * 5, 2) if empty_min > 0 else None

    # 2) Saat lensa ditutup → harus 0 deteksi & 0 announce
    cover_wins = _windows(marks, "cover", "uncover")
    cov_det = cov_ann = 0
    for (t0, t1) in cover_wins:
        for e in samples_between(samples, t0, t1):
            cov_det += len(e.get("dets") or [])
        cov_ann += sum(1 for a in navs if t0 <= a["ts"] <= t1)
    res["cover_windows"] = len(cover_wins)
    res["cover_detections"] = cov_det
    res["cover_announcements"] = cov_ann

    # 3) Re-announce objek diam + flapping (track 'static')
    statics = []
    segs = [s for s in build_segments(marks, session_end) if s["kind"] == "static" and s["end"]]
    for s in segs:
        lbl, t0, t1 = s["label"], s["start"], s["end"]
        ann_ts = [a["ts"] for a in navs if a["label"] == lbl and t0 <= a["ts"] <= t1]
        intervals = [round(ann_ts[i + 1] - ann_ts[i], 2) for i in range(len(ann_ts) - 1)]
        # flapping: hitung pergantian tier near<->far di stream untuk label ini
        tiers = [d.get("tier", "far")
                 for e in samples_between(samples, t0, t1)
                 for d in e.get("dets") or [] if d.get("label") == lbl]
        flips = sum(1 for i in range(len(tiers) - 1) if tiers[i] != tiers[i + 1])
        statics.append({
            "label": lbl, "dur_s": round(t1 - t0, 1),
            "announce_count": len(ann_ts),
            "median_interval_s": _r(pct(intervals, 0.5)),
            "tier_flips": flips,
        })
    res["static_tracks"] = statics

    res["checks"] = [
        _chk("phantom / 5 min (kosong)", res["phantom_per_5min"], "<=", T["B_phantom_per_5min"]),
        _chk("announce saat lensa tertutup", res["cover_announcements"], "<=", T["B_cover_zero"]),
        _chk("deteksi saat lensa tertutup", res["cover_detections"], "<=", T["B_cover_zero"]),
    ]
    return res


# ─── Blok D (rubrik manual) ─────────────────────────────────────────────────────

def block_d(sdir):
    path = os.path.join(sdir, "context_rubric.csv")
    if not os.path.exists(path):
        return {"skipped": True, "reason": f"isi dulu {path} (template tersedia)"}
    rows = []
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                rows.append({
                    "scene": row.get("scene", ""),
                    "n_key": float(row.get("n_key") or 0),
                    "n_named": float(row.get("n_named") or 0),
                    "n_halluc": float(row.get("n_halluc") or 0),
                    "pos_ok": float(row.get("pos_ok") or 0),
                    "useful": float(row.get("useful") or 0),
                })
            except ValueError:
                pass
    rows = [r for r in rows if r["n_key"] > 0]
    if not rows:
        return {"skipped": True, "reason": "rubrik kosong / belum diisi"}
    sk = sum(r["n_key"] for r in rows)
    sn = sum(r["n_named"] for r in rows)
    sh = sum(r["n_halluc"] for r in rows)
    res = {
        "scenes": len(rows),
        "key_recall": round(sn / sk, 3) if sk else None,
        "halluc_rate": round(sh / (sn + sh), 3) if (sn + sh) else 0.0,
        "pos_rate": round(mean([r["pos_ok"] for r in rows]), 3),
        "useful_avg": round(mean([r["useful"] for r in rows]), 2),
    }
    res["checks"] = [
        _chk("recall objek kunci", res["key_recall"], ">=", T["D_key_recall"], pctfmt=True),
        _chk("posisi benar", res["pos_rate"], ">=", T["D_pos"], pctfmt=True),
        _chk("hallucination rate", res["halluc_rate"], "<=", T["D_halluc_max"], pctfmt=True),
        _chk("kegunaan (1-5)", res["useful_avg"], ">=", T["D_useful"]),
    ]
    return res


# ─── Blok E (latency konteks dari aksi driver) ──────────────────────────────────

def block_e(marks):
    acts = [m for m in marks if m.get("kind") == "action"
            and m.get("tag") in ("describe", "describe1") and m.get("ok") is not False]
    acts = [a for a in acts if a.get("scene_id") is not None]
    if not acts:
        return {"skipped": True, "reason": "tidak ada aksi describe (jalankan driver.py describe)"}
    warm = [a for a in acts if a.get("source") == "cache"]
    cold = [a for a in acts if a.get("source") == "synth"]
    warm_ta = [a.get("to_audio_ms") for a in warm]
    cold_ta = [a.get("to_audio_ms") for a in cold]
    gem = [a.get("gemini_ms") for a in acts]
    cold_total = [(a.get("gemini_ms") or 0) + (a.get("to_audio_ms") or 0) for a in cold]
    res = {
        "describes": len(acts),
        "cache_hits": len(warm), "synths": len(cold),
        "hit_rate": round(len(warm) / len(acts), 2) if acts else None,
        "gemini_median_ms": _r(pct(gem, 0.5)),
        "warm_to_audio_median_ms": _r(pct(warm_ta, 0.5)),
        "warm_to_audio_p95_ms": _r(pct(warm_ta, 0.95)),
        "cold_total_median_ms": _r(pct(cold_total, 0.5)),
        "cold_total_p95_ms": _r(pct(cold_total, 0.95)),
    }
    res["checks"] = [
        _chk("warm to-audio median (ms)", res["warm_to_audio_median_ms"], "<=", T["E_warm_to_audio_ms"]),
        _chk("cold total p95 (ms)", res["cold_total_p95_ms"], "<=", T["E_cold_ms"]),
        _chk("cache hit-rate", res["hit_rate"], ">=", T["E_hit_rate"], pctfmt=True),
    ]
    return res


# ─── Blok G (reliability) ───────────────────────────────────────────────────────

def block_g(events, samples, marks, anns):
    res = {}
    # mode-switch
    ms = [m for m in marks if m.get("kind") == "action" and m.get("tag") == "modeswitch"]
    if ms:
        ok = sum(1 for m in ms if m.get("changed"))
        res["modeswitch_total"] = len(ms)
        res["modeswitch_ok"] = ok
        res["modeswitch_rate"] = round(ok / len(ms), 3)
    # crash proxy: status_fail
    res["status_fail_count"] = sum(1 for e in events if e.get("kind") == "status_fail")
    # thermal / fps health
    temps = [e.get("temp") for e in samples if e.get("temp") is not None]
    fpss = [e.get("fps") for e in samples if e.get("fps")]
    res["max_temp_c"] = _r(max(temps)) if temps else None
    res["min_fps"] = _r(min(fpss)) if fpss else None
    res["avg_fps"] = _r(mean(fpss)) if fpss else None

    # barge-in: setelah aksi describe1 label=barge, ada caption LOW (deskripsi)?
    barge = next((m for m in marks if m.get("kind") == "action"
                  and m.get("tag") == "describe1" and m.get("label") == "barge"), None)
    if barge:
        after = [a for a in anns if a["ts"] >= barge["ts"] and a["prio"] == "low"]
        res["barge_in_heard"] = len(after) > 0

    # network-drop: setelah describe1 label=netdown, caption mengandung 'koneksi'?
    netd = next((m for m in marks if m.get("kind") == "action"
                 and m.get("tag") == "describe1" and m.get("label") == "netdown"), None)
    if netd:
        after = [e for e in samples if e["ts"] >= netd["ts"]]
        offline_cue = any("koneksi" in ((e.get("caption") or {}).get("text") or "").lower()
                          for e in after[:60])
        res["network_offline_cue"] = offline_cue

    checks = []
    if "modeswitch_rate" in res:
        checks.append(_chk("mode-switch sukses", res["modeswitch_rate"], ">=", T["G_modeswitch_ok"], pctfmt=True))
    checks.append(_chk("status_fail (proxy crash)", res["status_fail_count"], "<=", 0))
    if res["max_temp_c"] is not None:
        checks.append(_chk("suhu max (°C)", res["max_temp_c"], "<=", T["thermal_max_c"]))
    if res["min_fps"] is not None:
        checks.append(_chk("FPS minimum", res["min_fps"], ">=", T["fps_floor"]))
    if "barge_in_heard" in res:
        checks.append(_chk("barge-in deskripsi kedengar", 1 if res["barge_in_heard"] else 0, ">=", 1))
    if "network_offline_cue" in res:
        checks.append(_chk("cue offline saat WiFi mati", 1 if res["network_offline_cue"] else 0, ">=", 1))
    res["checks"] = checks
    return res


# ─── Util penilaian ──────────────────────────────────────────────────────────────

def _majority(xs):
    if not xs:
        return None
    counts = {}
    for x in xs:
        counts[x] = counts.get(x, 0) + 1
    return max(counts, key=counts.get)


def _r(x, nd=1):
    if x is None:
        return None
    return round(x, nd)


def _chk(name, value, op, target, pctfmt=False):
    if value is None:
        return {"name": name, "value": None, "target": target, "op": op,
                "pass": None, "pctfmt": pctfmt}
    if op == ">=":
        ok = value >= target
    elif op == "<=":
        ok = value <= target
    else:
        ok = value == target
    return {"name": name, "value": value, "target": target, "op": op,
            "pass": ok, "pctfmt": pctfmt}


# ─── Pretty print ────────────────────────────────────────────────────────────────

def _fmt(v, pctfmt):
    if v is None:
        return "—"
    if pctfmt and isinstance(v, (int, float)):
        return f"{v*100:.0f}%"
    return f"{v}"


def print_report(rep):
    div = "═" * 66
    print(div)
    print(f"  FIELD BENCHMARK — sesi: {rep['session']}")
    print(f"  samples={rep['n_samples']}  marks={rep['n_marks']}  "
          f"durasi≈{rep['duration_s']}s")
    print(div)
    blocks = [("A", "Explorer — Akurasi & Keselamatan"),
              ("B", "Explorer — Anti-spam & Recovery"),
              ("D", "Konteks — Akurasi Deskripsi"),
              ("E", "Konteks — Latency & Cache"),
              ("G", "Reliability Lintas-Mode")]
    total = passed = 0
    for key, title in blocks:
        b = rep["blocks"].get(key)
        print(f"\n── Blok {key}: {title} " + "─" * max(0, 40 - len(title)))
        if not b or b.get("skipped"):
            print(f"   [dilewati] {b.get('reason') if b else 'tidak ada data'}")
            continue
        for c in b.get("checks", []):
            mark = "•" if c["pass"] is None else ("✓" if c["pass"] else "✗")
            if c["pass"] is not None:
                total += 1
                passed += 1 if c["pass"] else 0
            print(f"   {mark} {c['name']:<34} {_fmt(c['value'], c['pctfmt']):>8}  "
                  f"(target {c['op']} {_fmt(c['target'], c['pctfmt'])})")
    print("\n" + div)
    print(f"  CHECKS LULUS: {passed}/{total}")
    print(div)


# ─── Main ────────────────────────────────────────────────────────────────────────

def analyze(sdir):
    events, samples, marks = load_session(sdir)
    if not samples:
        return {"error": f"tidak ada sample di {sdir}/events.jsonl"}
    t0 = samples[0]["ts"]
    t1 = samples[-1]["ts"]
    anns = extract_announcements(samples)
    navs = nav_announcements(anns)

    rep = {
        "session": os.path.basename(sdir.rstrip("/\\")),
        "dir": sdir,
        "n_samples": len(samples),
        "n_marks": len(marks),
        "duration_s": round(t1 - t0, 1),
        "n_announcements": len(navs),
        "blocks": {
            "A": block_a(samples, marks, navs, t1),
            "B": block_b(samples, marks, navs, t1),
            "D": block_d(sdir),
            "E": block_e(marks),
            "G": block_g(events, samples, marks, anns),
        },
    }
    return rep


def main():
    # Konsol Windows kadang cp1252 — paksa UTF-8 supaya ═/✓/✗ tidak crash.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="I-Sora field analyze")
    ap.add_argument("--session", help="nama sesi (di bawah SESSION_ROOT)")
    ap.add_argument("--dir", help="folder sesi eksplisit")
    ap.add_argument("--json", action="store_true", help="cetak JSON saja")
    args = ap.parse_args()

    sdir = args.dir or (session_dir(args.session) if args.session else None)
    if not sdir or not os.path.isdir(sdir):
        print(f"folder sesi tidak ditemukan: {sdir}", file=sys.stderr)
        sys.exit(1)

    rep = analyze(sdir)
    if "error" in rep:
        print(rep["error"], file=sys.stderr)
        sys.exit(1)

    out_path = os.path.join(sdir, "report.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=2, ensure_ascii=False)

    if args.json:
        print(json.dumps(rep, indent=2, ensure_ascii=False))
    else:
        print_report(rep)
        print(f"\nReport JSON: {out_path}")


if __name__ == "__main__":
    main()

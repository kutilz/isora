#!/usr/bin/env python3
"""
AuralAI QRIS Benchmark & Stability Test v1
===========================================
Mengukur performa sistem QRIS detection dalam berbagai kondisi nyata.

Metrik yang diukur:
  • Time-to-detect   — dari frame masuk sampai konfirmasi baca (mean ± std)
  • Success rate     — per kondisi (normal / redup / shake / miring ±15°)
  • Guidance accuracy — apakah perintah kiri/kanan/atas/bawah geometrically benar?
  • False positive   — seberapa sering bukan-QRIS dianggap berhasil

Output:
  • CSV   : qris_benchmark_TIMESTAMP.csv   (satu baris per trial)
  • Report: qris_report_TIMESTAMP.txt      (ringkasan statistik)

Minimal 30 trial per analisis statistik valid (default: 10 trial × 3 QRIS × 4 kondisi).

Usage:
  python qris_benchmark.py                         # Mode otomatis (synthetic jika no maix)
  python qris_benchmark.py --synthetic             # Paksa synthetic
  python qris_benchmark.py --trials 15            # 15 trial per kondisi
  python qris_benchmark.py --no-guidance --no-fp  # Skip bagian opsional
  python qris_benchmark.py --condition normal     # Hanya satu kondisi
"""

import os, sys, time, csv, math, random, argparse
from datetime import datetime

try:
    from statistics import mean, stdev
except ImportError:
    def mean(lst): return sum(lst) / len(lst) if lst else 0
    def stdev(lst):
        if len(lst) < 2: return 0
        m = mean(lst)
        return math.sqrt(sum((x - m) ** 2 for x in lst) / (len(lst) - 1))

try:
    from maix import camera, image, nn
    MAIX_OK = True
except ImportError as e:
    print(f"[WARN] maix: {e} — synthetic mode aktif")
    MAIX_OK = False

try:
    from pyzbar.pyzbar import decode as _pyzbar_decode
    import PIL.Image as _PIL
    PYZBAR_OK = True
except ImportError:
    PYZBAR_OK = False

_DIR = os.path.dirname(os.path.abspath(__file__))

DIV  = "=" * 62
DIV2 = "-" * 62


# ─────────────────────────────────────────────────────────
# TEST CASE DEFINITIONS
# ─────────────────────────────────────────────────────────
QRIS_TEST_CASES = [
    {
        "id":           "QRIS_A",
        "desc":         "Nominal kecil — warung / pedagang kaki lima",
        "nominal":      "Rp 10.000",
        "merchant_type":"warung",
        # Synthetic: rasio kesulitan decode (1.0 = mudah)
        "difficulty":   1.0,
    },
    {
        "id":           "QRIS_B",
        "desc":         "Nominal besar — toko retail / minimarket",
        "nominal":      "Rp 500.000",
        "merchant_type":"retail",
        "difficulty":   1.05,
    },
    {
        "id":           "QRIS_C",
        "desc":         "Bebas nominal — scan & bayar (input sendiri)",
        "nominal":      None,
        "merchant_type":"umum",
        "difficulty":   1.10,
    },
]

CONDITIONS = [
    {
        "id":          "normal",
        "desc":        "Normal (cahaya ≥200 lux, stabil)",
        "success_prob": 0.97,
        "time_mean_ms": 340,
        "time_std_ms":  45,
    },
    {
        "id":          "dim",
        "desc":        "Redup (cahaya ~50 lux, gelap)",
        "success_prob": 0.78,
        "time_mean_ms": 580,
        "time_std_ms":  90,
    },
    {
        "id":          "shake",
        "desc":        "Shake (simulasi tangan bergetar tunanetra)",
        "success_prob": 0.65,
        "time_mean_ms": 720,
        "time_std_ms":  130,
    },
    {
        "id":          "tilt_15",
        "desc":        "Miring ±15° (sudut kemiringan kamera)",
        "success_prob": 0.82,
        "time_mean_ms": 460,
        "time_std_ms":  80,
    },
]

GUIDANCE_POSITIONS = [
    ("center",  ["sudah_tepat"], "Letakkan QRIS di TENGAH frame"),
    ("left",    ["gerak_kanan"], "Letakkan QRIS di sisi KIRI frame   → sistem harus bilang 'gerak kanan'"),
    ("right",   ["gerak_kiri"], "Letakkan QRIS di sisi KANAN frame  → sistem harus bilang 'gerak kiri'"),
    ("top",     ["gerak_bawah"],"Letakkan QRIS di bagian ATAS frame → sistem harus bilang 'gerak bawah'"),
    ("bottom",  ["gerak_atas"], "Letakkan QRIS di bagian BAWAH frame→ sistem harus bilang 'gerak atas'"),
]


# ─────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────
def ts():      return time.time()
def ts_ms():   return time.time() * 1000.0
def now_str(): return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def pr(label, val=""):
    if val: print(f"  {label:<44} {val}")
    else:   print(f"  {label}")

def psec(title):
    print(); print(DIV); print(f"  {title}"); print(DIV)

def percentile(lst, p):
    if not lst: return 0
    s = sorted(lst)
    idx = int(math.ceil(len(s) * p / 100)) - 1
    return s[max(0, idx)]


# ─────────────────────────────────────────────────────────
# OUTPUT FILES
# ─────────────────────────────────────────────────────────
def init_output():
    ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path    = os.path.join(_DIR, f"qris_benchmark_{ts_str}.csv")
    report_path = os.path.join(_DIR, f"qris_report_{ts_str}.txt")

    with open(csv_path, "w", newline="") as f:
        csv.writer(f).writerow([
            "timestamp", "trial_num", "qris_id", "condition",
            "detected", "time_to_detect_ms", "result_valid",
            "guidance_expected", "guidance_actual", "guidance_correct",
            "is_false_positive", "notes",
        ])
    return csv_path, report_path

def append_trial(csv_path, **kw):
    with open(csv_path, "a", newline="") as f:
        csv.writer(f).writerow([
            kw.get("timestamp", now_str()),
            kw.get("trial_num", ""),
            kw.get("qris_id", ""),
            kw.get("condition", ""),
            "Y" if kw.get("detected") else "N",
            f"{kw.get('time_ms', 0):.1f}",
            "Y" if kw.get("valid") else "N",
            kw.get("guidance_expected", ""),
            kw.get("guidance_actual", ""),
            "Y" if kw.get("guidance_correct") else ("N" if kw.get("guidance_correct") is False else ""),
            "Y" if kw.get("is_fp") else "N",
            kw.get("notes", ""),
        ])


# ─────────────────────────────────────────────────────────
# QR DECODE PIPELINE
# ─────────────────────────────────────────────────────────
def attempt_qr_decode_maix(img):
    """
    Coba decode QR dari maix.image. Returns (detected, data, decode_ms).
    Coba tiga method secara berurutan.
    """
    t0 = ts_ms()

    # 1. MaixPy built-in QR (v2.x+)
    try:
        from maix import qr
        results = qr.detect(img)
        if results:
            return True, getattr(results[0], "data", str(results[0])), ts_ms() - t0
    except (ImportError, AttributeError, Exception):
        pass

    # 2. pyzbar via PIL
    if PYZBAR_OK:
        try:
            raw = bytes(img.to_bytes())
            w, h = img.width(), img.height()
            pil  = _PIL.frombytes("RGB", (w, h), raw)
            codes = _pyzbar_decode(pil)
            if codes:
                return True, codes[0].data.decode("utf-8", errors="replace"), ts_ms() - t0
        except Exception:
            pass

    # 3. nn.QRCode model (jika ada)
    try:
        from maix import nn as _nn
        qr_model = _nn.QRCode()
        results  = qr_model.detect(img)
        if results:
            return True, str(results[0]), ts_ms() - t0
    except (ImportError, AttributeError, Exception):
        pass

    return False, None, ts_ms() - t0


def validate_qris_data(data):
    """QRIS valid selalu dimulai '000201' (EMV QR Code standard)."""
    if not data: return False
    return data.startswith("000201") or data.startswith("00020101")


# ─────────────────────────────────────────────────────────
# SYNTHETIC SIMULATE
# ─────────────────────────────────────────────────────────
def synthetic_trial(condition, qris_case):
    """
    Simulasikan satu trial tanpa kamera nyata.
    Returns (detected, valid, time_ms).
    """
    c = condition
    q = qris_case

    # Waktu decode ~ Gaussian × difficulty factor
    base_time = random.gauss(c["time_mean_ms"], c["time_std_ms"])
    time_ms   = max(80, base_time * q["difficulty"])

    # Probabilitas sukses direduksi sedikit oleh difficulty
    prob = c["success_prob"] / q["difficulty"]
    detected = random.random() < prob
    valid    = detected  # dalam synthetic: jika terdeteksi, data valid

    return detected, valid, time_ms


# ─────────────────────────────────────────────────────────
# GUIDANCE GEOMETRY
# ─────────────────────────────────────────────────────────
def compute_guidance(qr_cx_px, qr_cy_px, frame_w, frame_h, tolerance=0.15):
    """
    Hitung perintah guidance dari posisi QR di frame.
    Tolerance: fraksi frame yang dianggap 'sudah tepat'.
    Returns: list of direction strings.
    """
    dx = (qr_cx_px / frame_w) - 0.5
    dy = (qr_cy_px / frame_h) - 0.5

    commands = []
    if abs(dx) < tolerance and abs(dy) < tolerance:
        commands.append("sudah_tepat")
    else:
        if dx < -tolerance: commands.append("gerak_kanan")
        elif dx > tolerance: commands.append("gerak_kiri")
        if dy < -tolerance: commands.append("gerak_bawah")
        elif dy > tolerance: commands.append("gerak_atas")

    return commands


def synthetic_qr_position(pos_name, frame_w=320, frame_h=224):
    """Kembalikan (cx, cy) untuk posisi known dalam synthetic test."""
    mapping = {
        "center": (frame_w * 0.50, frame_h * 0.50),
        "left":   (frame_w * 0.15, frame_h * 0.50),
        "right":  (frame_w * 0.85, frame_h * 0.50),
        "top":    (frame_w * 0.50, frame_h * 0.12),
        "bottom": (frame_w * 0.50, frame_h * 0.88),
    }
    return mapping.get(pos_name, (frame_w * 0.5, frame_h * 0.5))


# ─────────────────────────────────────────────────────────
# SECTION 1 — MAIN BENCHMARK LOOP
# ─────────────────────────────────────────────────────────
def run_detection_benchmark(cam, csv_path, trials_per_cond,
                            conditions_filter=None, live_mode=False):
    """
    Loop utama: setiap kondisi × setiap QRIS × trials_per_cond trial.
    Returns: dict condition_id → list of per-case result dicts.
    """
    all_results = {}
    trial_num   = 0

    active_conditions = [
        c for c in CONDITIONS
        if conditions_filter is None or c["id"] in conditions_filter
    ]

    for cond in active_conditions:
        cond_id   = cond["id"]
        cond_desc = cond["desc"]

        print(); print(DIV2)
        pr(f"KONDISI: {cond_desc}")

        if live_mode:
            try: input("  Atur kondisi pencahayaan/posisi, tekan Enter ketika siap... ")
            except EOFError: pass

        cond_results = []

        for qris in QRIS_TEST_CASES:
            qris_id = qris["id"]
            print()
            pr(f"QRIS: {qris_id} — {qris['desc']}")
            pr("Nominal", qris["nominal"] or "bebas")

            if live_mode:
                try: input(f"  Tunjukkan {qris_id} ke kamera, tekan Enter... ")
                except EOFError: pass

            detect_times = []
            successes    = 0

            for t in range(trials_per_cond):
                trial_num += 1

                if live_mode and cam:
                    img = cam.read()
                    t_start = ts_ms()
                    detected, data, decode_ms = attempt_qr_decode_maix(img)
                    time_ms = ts_ms() - t_start + decode_ms
                    valid   = validate_qris_data(data)
                else:
                    detected, valid, time_ms = synthetic_trial(cond, qris)

                if detected and valid:
                    successes += 1
                    detect_times.append(time_ms)

                status = "✓" if (detected and valid) else "✗"
                print(f"    [{t+1:02d}/{trials_per_cond}]  {status}  {time_ms:.0f}ms  "
                      f"{'detected+valid' if valid else ('detected+invalid' if detected else 'not_detected')}")

                append_trial(csv_path,
                    timestamp=now_str(), trial_num=trial_num,
                    qris_id=qris_id, condition=cond_id,
                    detected=detected, time_ms=time_ms, valid=valid,
                    notes="live" if live_mode else "synthetic")

                time.sleep(0.05)

            success_rate = successes / trials_per_cond * 100
            if detect_times:
                avg_ms = mean(detect_times)
                std_ms = stdev(detect_times) if len(detect_times) > 1 else 0
                p50    = percentile(detect_times, 50)
                p95    = percentile(detect_times, 95)
                p99    = percentile(detect_times, 99)
                min_ms = min(detect_times)
                max_ms = max(detect_times)
            else:
                avg_ms = std_ms = p50 = p95 = p99 = min_ms = max_ms = 0

            case_result = {
                "qris_id": qris_id, "condition": cond_id,
                "trials": trials_per_cond, "successes": successes,
                "success_rate": success_rate,
                "avg_ms": avg_ms, "std_ms": std_ms,
                "p50_ms": p50, "p95_ms": p95, "p99_ms": p99,
                "min_ms": min_ms, "max_ms": max_ms,
            }
            cond_results.append(case_result)

            verdict = "✓ OK" if success_rate >= 90 else ("⚠ WARNING" if success_rate >= 70 else "✗ FAIL")
            pr(f"  → {qris_id}/{cond_id}",
               f"rate={success_rate:.0f}%  avg={avg_ms:.0f}ms  ±{std_ms:.0f}ms  "
               f"p95={p95:.0f}ms  p99={p99:.0f}ms  {verdict}")

        all_results[cond_id] = cond_results

    return all_results, trial_num


# ─────────────────────────────────────────────────────────
# SECTION 2 — GUIDANCE ACCURACY
# ─────────────────────────────────────────────────────────
def test_guidance_accuracy(cam, csv_path, live_mode=False):
    print(); print(DIV2)
    pr("SECTION 2 — Guidance Command Accuracy")
    pr("Verifikasi: apakah perintah arah secara geometris benar?")

    results = []
    FRAME_W, FRAME_H = 320, 224

    for pos_name, expected_cmds, instruction in GUIDANCE_POSITIONS:
        pr(f"  → {instruction}")

        if live_mode and cam:
            try: input("     Siap? Tekan Enter... ")
            except EOFError: pass
            img      = cam.read()
            detected, _, _ = attempt_qr_decode_maix(img)
            # Posisi nyata perlu bounding box dari QR detector
            # Untuk sekarang, anggap tengah frame jika terdeteksi
            qr_cx, qr_cy = FRAME_W // 2, FRAME_H // 2
        else:
            detected = True
            qr_cx, qr_cy = synthetic_qr_position(pos_name, FRAME_W, FRAME_H)

        actual_cmds = compute_guidance(qr_cx, qr_cy, FRAME_W, FRAME_H) if detected else ["tidak_terdeteksi"]
        correct     = set(expected_cmds) == set(actual_cmds)

        pr(f"  [{pos_name:<8}] expected={expected_cmds}",
           ("✓ BENAR" if correct else f"✗ SALAH (actual={actual_cmds})"))

        append_trial(csv_path,
            timestamp=now_str(), qris_id="GUIDANCE_TEST", condition=pos_name,
            detected=detected, time_ms=0, valid=correct,
            guidance_expected=",".join(expected_cmds),
            guidance_actual=",".join(actual_cmds),
            guidance_correct=correct,
            notes="guidance_test")

        results.append({
            "position": pos_name, "expected": expected_cmds,
            "actual": actual_cmds, "correct": correct, "detected": detected,
        })

    acc = sum(1 for r in results if r["correct"]) / len(results) * 100 if results else 0
    print()
    pr("Guidance Accuracy",
       f"{acc:.1f}%  ({sum(1 for r in results if r['correct'])}/{len(results)} benar)")
    return results


# ─────────────────────────────────────────────────────────
# SECTION 3 — FALSE POSITIVE RATE
# ─────────────────────────────────────────────────────────
def test_false_positive(cam, csv_path, trials=20, live_mode=False):
    print(); print(DIV2)
    pr("SECTION 3 — False Positive Rate")
    pr(f"Arahkan kamera ke objek NON-QRIS selama {trials} trial")

    if live_mode and cam:
        try: input("  Siap? (arahkan ke non-QRIS) Tekan Enter... ")
        except EOFError: pass

    false_positives = 0

    for i in range(trials):
        if live_mode and cam:
            img = cam.read()
            detected, data, _ = attempt_qr_decode_maix(img)
            fp = detected and validate_qris_data(data)
        else:
            # Synthetic: ~3% false positive rate
            fp = random.random() < 0.03

        if fp:
            false_positives += 1

        status = "FP!" if fp else "OK"
        print(f"    [{i+1:02d}/{trials}]  {status}")

        append_trial(csv_path,
            timestamp=now_str(), trial_num=i+1,
            qris_id="FP_TEST", condition="non_qris",
            detected=fp, time_ms=0, valid=False,
            is_fp=fp, notes="false_positive_test")

        time.sleep(0.05)

    fp_rate = false_positives / trials * 100 if trials > 0 else 0
    print()
    pr("False Positive Rate",
       f"{fp_rate:.1f}%  ({false_positives}/{trials})")

    if fp_rate == 0:
        pr("Verdict", "✓ Excellent — 0% FP (sempurna)")
    elif fp_rate <= 5:
        pr("Verdict", f"✓ Acceptable — FP rate {fp_rate:.1f}% (≤5%)")
    else:
        pr("Verdict", f"✗ Tinggi — FP rate {fp_rate:.1f}% (>5% — perlu tuning threshold)")

    return fp_rate, false_positives


# ─────────────────────────────────────────────────────────
# FINAL REPORT
# ─────────────────────────────────────────────────────────
def print_final_report(all_results, guidance_results, fp_rate, fp_count,
                        total_trials, csv_path, report_path):
    psec("LAPORAN BENCHMARK QRIS — AuralAI")

    lines = [DIV, "  LAPORAN BENCHMARK QRIS — AuralAI", f"  {now_str()}", DIV]

    def prl(label="", val=""):
        line = f"  {label:<44} {val}" if val else f"  {label}"
        print(line); lines.append(line)

    prl("Total trial dijalankan", str(total_trials))
    prl("Output CSV", csv_path)

    # ── Time-to-detect global
    all_times = []
    for cond_id, results in all_results.items():
        for r in results:
            if r["avg_ms"] > 0:
                all_times.append(r["avg_ms"])

    prl()
    prl("── TIME-TO-DETECT (semua kondisi, semua QRIS) ──")
    if all_times:
        prl("  Mean",    f"{mean(all_times):.0f} ms")
        prl("  Std Dev", f"±{stdev(all_times) if len(all_times)>1 else 0:.0f} ms")
        prl("  Min",     f"{min(all_times):.0f} ms")
        prl("  Max",     f"{max(all_times):.0f} ms")
    else:
        prl("  Tidak ada data (semua trial gagal)")

    # ── Per-kondisi breakdown
    prl()
    prl("── SUCCESS RATE & LATENCY PER KONDISI ──")
    for cond in CONDITIONS:
        cid = cond["id"]
        results = all_results.get(cid, [])
        if not results: continue
        avg_rate = mean(r["success_rate"] for r in results)
        valid_r  = [r for r in results if r["avg_ms"] > 0]
        avg_ms   = mean(r["avg_ms"] for r in valid_r) if valid_r else 0
        avg_std  = mean(r["std_ms"] for r in valid_r) if valid_r else 0
        avg_p95  = mean(r["p95_ms"] for r in valid_r) if valid_r else 0
        verdict  = "✓ OK" if avg_rate >= 90 else ("⚠ WARNING" if avg_rate >= 70 else "✗ FAIL")
        prl(f"  {cond['desc'][:38]}",
            f"rate={avg_rate:.0f}%  avg={avg_ms:.0f}ms  ±{avg_std:.0f}ms  p95={avg_p95:.0f}ms  {verdict}")

    # ── Per-QRIS breakdown
    prl()
    prl("── SUCCESS RATE PER QRIS (lintas kondisi) ──")
    for qris in QRIS_TEST_CASES:
        qid = qris["id"]
        rates = []
        for results in all_results.values():
            for r in results:
                if r["qris_id"] == qid:
                    rates.append(r["success_rate"])
        if rates:
            prl(f"  {qid} — {qris['desc'][:30]}",
                f"avg rate={mean(rates):.0f}%  (min={min(rates):.0f}%  max={max(rates):.0f}%)")

    # ── Guidance accuracy
    prl()
    prl("── GUIDANCE COMMAND ACCURACY ──")
    if guidance_results:
        n_correct = sum(1 for r in guidance_results if r["correct"])
        n_total   = len(guidance_results)
        acc       = n_correct / n_total * 100
        prl("  Accuracy", f"{acc:.1f}%  ({n_correct}/{n_total} benar)")
        for r in guidance_results:
            status = "✓" if r["correct"] else f"✗ actual={r['actual']}"
            prl(f"  [{r['position']:<8}] expected={r['expected']}", status)
    else:
        prl("  (dilewati)")

    # ── False positive
    prl()
    prl("── FALSE POSITIVE RATE ──")
    prl("  Rate", f"{fp_rate:.1f}%  ({fp_count} positif palsu)")
    if fp_rate == 0:     prl("  Verdict", "✓ Excellent")
    elif fp_rate <= 5:   prl("  Verdict", f"✓ Acceptable (≤5%)")
    else:                prl("  Verdict", f"✗ Tinggi (>5%) — perlu tuning")

    # ── Rekomendasi
    prl()
    prl("── REKOMENDASI ──")
    recs = 0
    for cond in CONDITIONS:
        cid = cond["id"]
        results = all_results.get(cid, [])
        if results:
            avg_rate = mean(r["success_rate"] for r in results)
            if avg_rate < 70:
                prl(f"  ⚠ Kondisi '{cid}' success rate rendah ({avg_rate:.0f}%)")
                prl(f"    → Tambah exposure time atau coba decode ulang sebelum bilang gagal")
                recs += 1
            elif avg_rate < 90:
                prl(f"  ⚠ Kondisi '{cid}' belum 90% ({avg_rate:.0f}%) — pertimbangkan torch/LED")
                recs += 1

    if all_times and mean(all_times) > 1000:
        prl(f"  ⚠ Latency rata-rata {mean(all_times):.0f}ms > 1 detik")
        prl(f"    → Optimasi: coba decode lebih awal, atau multi-frame voting")
        recs += 1

    if fp_rate > 5:
        prl(f"  ⚠ False positive {fp_rate:.1f}% — naikkan confidence threshold atau validasi EMV prefix")
        recs += 1

    if recs == 0:
        prl("  ✓ Semua metrik dalam batas akseptabel")

    prl(); print(DIV); lines.append(DIV)

    # Simpan ke file
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    pr("Report disimpan ke", report_path)


# ─────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="AuralAI QRIS Benchmark")
    parser.add_argument("--synthetic",    action="store_true",
                        help="Paksa mode synthetic (tanpa kamera)")
    parser.add_argument("--trials",       type=int, default=10,
                        help="Trial per kondisi per QRIS (default: 10)")
    parser.add_argument("--condition",    nargs="+",
                        choices=["normal","dim","shake","tilt_15"],
                        help="Jalankan hanya kondisi tertentu")
    parser.add_argument("--no-guidance",  action="store_true",
                        help="Skip guidance accuracy test")
    parser.add_argument("--no-fp",        action="store_true",
                        help="Skip false positive test")
    parser.add_argument("--fp-trials",    type=int, default=20,
                        help="Trial untuk false positive test (default: 20)")
    args = parser.parse_args()

    psec("AuralAI QRIS Benchmark & Stability Test v1")

    live_mode = MAIX_OK and not args.synthetic
    pr("Mode",          "Live (MaixCAM)" if live_mode else "Synthetic (simulasi)")
    pr("pyzbar",        "Tersedia" if PYZBAR_OK else "Tidak ada (gunakan maix QR atau synthetic)")
    pr("Kondisi aktif", ", ".join(args.condition) if args.condition else "semua (4 kondisi)")
    pr("QRIS test case",f"{len(QRIS_TEST_CASES)} kasus")
    pr("Trial/kondisi", str(args.trials))
    n_cond = len(args.condition) if args.condition else len(CONDITIONS)
    pr("Estimasi total", f"{n_cond * len(QRIS_TEST_CASES) * args.trials} trial deteksi")

    csv_path, report_path = init_output()
    pr("CSV output",    csv_path)

    cam = None
    if live_mode:
        try:
            cam = camera.Camera(320, 240)
            pr("Camera", "OK (320×240)")
        except Exception as ex:
            pr("Camera error", str(ex))
            pr("Fallback ke synthetic")
            live_mode = False

    print()

    # ── Section 1: Detection benchmark
    all_results, total_trials = run_detection_benchmark(
        cam, csv_path, args.trials,
        conditions_filter=args.condition,
        live_mode=live_mode,
    )

    # ── Section 2: Guidance accuracy
    guidance_results = []
    if not args.no_guidance:
        guidance_results = test_guidance_accuracy(cam, csv_path, live_mode)

    # ── Section 3: False positive
    fp_rate, fp_count = 0.0, 0
    if not args.no_fp:
        fp_rate, fp_count = test_false_positive(
            cam, csv_path, trials=args.fp_trials, live_mode=live_mode
        )

    # ── Final report
    print_final_report(
        all_results, guidance_results, fp_rate, fp_count,
        total_trials, csv_path, report_path
    )

    if cam:
        del cam


if __name__ == "__main__":
    main()

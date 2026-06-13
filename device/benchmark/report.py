#!/usr/bin/env python3
"""
Safety & Reliability Index — Laporan kompilasi dari 4 uji benchmark.

Membaca hasil dari:
  /root/logs/bench_t1_latency.json
  /root/logs/bench_t2_accuracy.json
  /root/logs/bench_t3_audio.json
  /root/logs/bench_t4_stability.json

Menghitung Safety & Reliability Index (0–100) dengan bobot:
  T1 Latency    35%  (safety-critical: kecepatan respons)
  T2 Accuracy   30%  (safety-critical: deteksi rintangan)
  T3 Audio      20%  (fungsionalitas inti)
  T4 Stability  15%  (keandalan jangka panjang)

Grading:
  A  ≥ 90   Siap produksi — keselamatan terjamin
  B  75–89  Layak digunakan — peningkatan minor disarankan
  C  60–74  Gunakan dengan pengawasan — perlu perbaikan
  D  40–59  Tidak aman untuk produksi — perbaikan signifikan diperlukan
  F   < 40  Gagal — jangan digunakan
"""

import os
import json
import time
from typing import Optional

RESULTS_DIR   = "/root/logs"
REPORT_FILE   = "/root/logs/safety_index_report.json"

T1_FILE = os.path.join(RESULTS_DIR, "bench_t1_latency.json")
T2_FILE = os.path.join(RESULTS_DIR, "bench_t2_accuracy.json")
T3_FILE = os.path.join(RESULTS_DIR, "bench_t3_audio.json")
T4_FILE = os.path.join(RESULTS_DIR, "bench_t4_stability.json")

WEIGHTS = {"T1": 0.35, "T2": 0.30, "T3": 0.20, "T4": 0.15}

GRADES = [
    (90, "A", "Siap produksi — keselamatan terjamin"),
    (75, "B", "Layak digunakan — peningkatan minor disarankan"),
    (60, "C", "Gunakan dengan pengawasan — perlu perbaikan"),
    (40, "D", "Tidak aman untuk produksi — perbaikan signifikan diperlukan"),
    ( 0, "F", "Gagal — jangan digunakan"),
]


def _load(path: str) -> Optional[dict]:
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def _grade(index: float) -> tuple:
    for threshold, grade, desc in GRADES:
        if index >= threshold:
            return grade, desc
    return "F", GRADES[-1][2]


def _bar(score: float, width: int = 30) -> str:
    filled = round(score / 100 * width)
    return "█" * filled + "░" * (width - filled)


def compile_report(emit_cb=None) -> dict:
    def emit(text="", tag="plain"):
        if emit_cb:
            emit_cb(text, tag)
        print(text, flush=True)

    emit("═" * 64, "div")
    emit("SAFETY & RELIABILITY INDEX — AuralAI SDK", "section")
    emit("═" * 64, "div")

    # ── Load results ──────────────────────────────────────────────────────────
    t1 = _load(T1_FILE)
    t2 = _load(T2_FILE)
    t3 = _load(T3_FILE)
    t4 = _load(T4_FILE)

    tests = {"T1": t1, "T2": t2, "T3": t3, "T4": t4}
    names = {
        "T1": "End-to-End Latency",
        "T2": "Detection Accuracy",
        "T3": "Audio Priority",
        "T4": "Hardware Stability",
    }

    # ── Per-test summary ──────────────────────────────────────────────────────
    emit()
    weighted_sum   = 0.0
    weighted_total = 0.0
    missing_tests  = []
    skipped_tests  = []
    per_test       = {}

    for key in ("T1", "T2", "T3", "T4"):
        data   = tests[key]
        weight = WEIGHTS[key]
        name   = names[key]

        if data is None:
            emit(f"  {key} {name:<28} [hasil tidak ditemukan]", "warn")
            missing_tests.append(key)
            per_test[key] = {"score": None, "passed": None, "missing": True}
            continue

        if data.get("skipped"):
            score = None
            emit(f"  {key} {name:<28} [dilewati — {data.get('reason','?')}]", "warn")
            skipped_tests.append(key)
            per_test[key] = {"score": None, "passed": None, "skipped": True,
                             "reason": data.get("reason")}
            continue

        score  = data.get("score", 0)
        passed = data.get("passed", False)
        bar    = _bar(score)

        emit(f"  {key} {name:<28} {bar} {score:3.0f}/100  "
             f"{'PASS' if passed else 'FAIL'}", "ok" if passed else "err")

        per_test[key] = {"score": score, "passed": passed}
        weighted_sum   += score * weight
        weighted_total += weight

    # ── Safety Index ──────────────────────────────────────────────────────────
    if weighted_total == 0:
        emit("\n  ✗ Tidak ada data uji — jalankan benchmark terlebih dahulu", "err")
        index = 0.0
    else:
        # Skipped tests get a neutral 70 so they don't tank the score,
        # but missing tests (never run) get 0.
        for key in skipped_tests:
            weighted_sum   += 70 * WEIGHTS[key]
            weighted_total += WEIGHTS[key]
        index = round(weighted_sum / weighted_total, 1)

    grade, grade_desc = _grade(index)

    emit()
    emit("─" * 64, "div")
    emit(f"  Safety & Reliability Index  :  {index:.1f} / 100", "section")
    emit(f"  Grade                       :  {grade}  — {grade_desc}")
    emit("─" * 64, "div")

    # ── Rekomendasi ───────────────────────────────────────────────────────────
    recommendations = []

    if t1 and not t1.get("skipped"):
        if not t1.get("passed"):
            p95 = t1.get("p95_ms", 999)
            recommendations.append(
                f"[T1] Latensi p95={p95}ms melebihi {t1.get('pass_threshold',300)}ms. "
                "Coba: turunkan resolusi kamera (input_width/input_height di config.json) "
                "atau pakai model lebih ringan."
            )

    if t2 and not t2.get("skipped") and not t2.get("passed"):
        recall = t2.get("min_critical_recall", 0)
        recommendations.append(
            f"[T2] Recall kritis {recall:.0%} < 95%. "
            "Coba: turunkan conf_threshold (misal ke 0.35) di config.json, "
            "atau uji dengan pencahayaan yang lebih baik."
        )

    if t3 and not t3.get("passed"):
        rate = t3.get("interrupt_rate", 0)
        recommendations.append(
            f"[T3] Interrupt rate {rate:.0%} < 100%. "
            "Periksa implementasi AudioManager._interrupt event."
        )

    if t4 and not t4.get("skipped") and not t4.get("passed"):
        min_fps = t4.get("min_fps", 0)
        temp    = t4.get("max_temp_c", 0)
        recommendations.append(
            f"[T4] Min FPS={min_fps:.1f} (perlu ≥15), suhu max={temp:.1f}°C. "
            "Coba: tambah heatsink, pastikan ventilasi cukup, "
            "atau aktifkan thermal_throttle_fps di config.json."
        )

    if missing_tests:
        recommendations.append(
            f"Uji {', '.join(missing_tests)} belum pernah dijalankan — "
            "indeks tidak akurat. Jalankan run_all.py untuk laporan lengkap."
        )

    if skipped_tests:
        recommendations.append(
            f"[T2] Buat test dataset di /root/test_images/ agar akurasi "
            "deteksi bisa diukur secara nyata."
        )

    if recommendations:
        emit()
        emit("  REKOMENDASI:", "section")
        for i, rec in enumerate(recommendations, 1):
            emit(f"  {i}. {rec}", "warn")

    emit()

    # ── Summary table ─────────────────────────────────────────────────────────
    report = {
        "safety_index":      index,
        "grade":             grade,
        "grade_description": grade_desc,
        "weights":           WEIGHTS,
        "tests":             per_test,
        "recommendations":   recommendations,
        "missing_tests":     missing_tests,
        "skipped_tests":     skipped_tests,
        "weighted_total":    round(weighted_total, 4),
        "timestamp":         time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source_files": {
            "T1": T1_FILE, "T2": T2_FILE, "T3": T3_FILE, "T4": T4_FILE,
        },
    }

    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(REPORT_FILE, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    emit(f"  Laporan disimpan: {REPORT_FILE}")

    return report


if __name__ == "__main__":
    compile_report()

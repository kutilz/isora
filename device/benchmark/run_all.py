#!/usr/bin/env python3
"""
AuralAI Standardized Benchmark Suite — Entry Point
====================================================
Menjalankan ke-4 uji secara berurutan dan menghasilkan laporan akhir.

Penggunaan:
  python3 device/benchmark/run_all.py [options]

Options:
  --tests T1,T2,T3,T4   Uji yang dijalankan (default: semua)
  --t1-frames  N         Jumlah frame untuk T1 (default: 100)
  --t4-duration S        Durasi T4 dalam detik (default: 600 = 10 menit)
                         Gunakan 10800 untuk uji 3 jam penuh
  --report-only          Hanya buat laporan dari hasil yang sudah ada

Output:
  /root/logs/bench_t1_latency.json
  /root/logs/bench_t2_accuracy.json
  /root/logs/bench_t3_audio.json
  /root/logs/bench_t4_stability.json
  /root/logs/safety_index_report.json
  /tmp/bench_suite_progress.json        (live progress untuk web UI)
"""

import sys, os, time, json, argparse
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

PROGRESS_FILE = "/tmp/bench_suite_progress.json"


def _progress(step: str, total: int, current: int,
              results: dict, running: bool = True):
    state = {
        "running":  running,
        "step":     step,
        "total":    total,
        "current":  current,
        "pct":      round(current / total * 100) if total else 0,
        "results":  results,
        "updated":  time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    try:
        with open(PROGRESS_FILE, "w") as f:
            json.dump(state, f)
    except Exception:
        pass
    return state


def _divider(char="═", width=64):
    print(char * width, flush=True)


def main():
    parser = argparse.ArgumentParser(description="AuralAI Benchmark Suite")
    parser.add_argument("--tests",       default="T1,T2,T3,T4",
                        help="Comma-separated tests to run (T1,T2,T3,T4)")
    parser.add_argument("--t1-frames",   type=int,   default=100)
    parser.add_argument("--t4-duration", type=float, default=600,
                        help="T4 duration seconds (default 600, full=10800)")
    parser.add_argument("--report-only", action="store_true",
                        help="Skip tests, only compile report from existing results")
    args = parser.parse_args()

    selected = [t.strip().upper() for t in args.tests.split(",")]

    _divider()
    print("AuralAI Standardized Benchmark Suite", flush=True)
    print(f"Running: {', '.join(selected)}", flush=True)
    print(f"Started: {time.strftime('%Y-%m-%dT%H:%M:%S')}", flush=True)
    _divider()

    results_accum = {}
    n_tests  = len(selected) + 1  # +1 for report step
    step_idx = 0

    if not args.report_only:
        # ── T1: Latency ────────────────────────────────────────────────────────
        if "T1" in selected:
            step_idx += 1
            _progress("T1_Latency", n_tests, step_idx, results_accum)
            from benchmark.t1_latency import run as run_t1
            r = run_t1(n_frames=args.t1_frames)
            results_accum["T1"] = r
            _progress("T1_done", n_tests, step_idx, results_accum)

        # ── T2: Accuracy ───────────────────────────────────────────────────────
        if "T2" in selected:
            step_idx += 1
            _progress("T2_Accuracy", n_tests, step_idx, results_accum)
            from benchmark.t2_accuracy import run as run_t2
            r = run_t2()
            results_accum["T2"] = r
            _progress("T2_done", n_tests, step_idx, results_accum)

        # ── T3: Audio ──────────────────────────────────────────────────────────
        if "T3" in selected:
            step_idx += 1
            _progress("T3_Audio", n_tests, step_idx, results_accum)
            from benchmark.t3_audio import run as run_t3
            r = run_t3()
            results_accum["T3"] = r
            _progress("T3_done", n_tests, step_idx, results_accum)

        # ── T4: Stability ──────────────────────────────────────────────────────
        if "T4" in selected:
            step_idx += 1
            _progress("T4_Stability", n_tests, step_idx, results_accum)
            from benchmark.t4_stability import run as run_t4
            r = run_t4(duration_s=args.t4_duration)
            results_accum["T4"] = r
            _progress("T4_done", n_tests, step_idx, results_accum)

    # ── Report ─────────────────────────────────────────────────────────────────
    step_idx += 1
    _progress("Report", n_tests, step_idx, results_accum)

    _divider()
    from benchmark.report import compile_report
    report = compile_report()
    results_accum["report"] = report

    _progress("done", n_tests, n_tests, results_accum, running=False)

    _divider()
    print(f"Safety & Reliability Index: {report['safety_index']}/100  "
          f"Grade: {report['grade']}", flush=True)
    print(f"Report: /root/logs/safety_index_report.json", flush=True)
    _divider()

    return report


if __name__ == "__main__":
    main()

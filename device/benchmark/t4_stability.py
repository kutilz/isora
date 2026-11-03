#!/usr/bin/env python3
"""
Test 4 — Hardware Stability (Endurance & Thermal)
===================================================
Menjalankan full pipeline (cam → NPU → JPEG) dalam durasi tertentu
dan merekam metrik per interval:
  - FPS rata-rata per interval
  - Latensi per frame (avg / p50 / p95 / min / max) dalam interval
  - Suhu CPU/NPU
  - RAM tersedia + terpakai
  - Load average
  - Throttle events (FPS turun >25% dari baseline)
  - Crash events (exception yang dipulihkan)

Standar Kelulusan:
  - Durasi penuh tanpa hard crash (exception tidak tertangani → 0)
  - FPS minimum (min_fps_floor) sepanjang uji >= 15 FPS

Score:
  base 50 (no crash) + 50 × (1 − max(0, min_fps_target − avg_fps) / min_fps_target)
  Dikurangi 10 per throttle event (min 0)

Default durasi: 600 detik (10 menit) — untuk quick test.
Gunakan --duration 10800 untuk uji 3 jam penuh.

Sampling: --interval 5 memberi 720 titik untuk uji 1 jam (cukup rapat untuk
grafik); tiap sampel di-append ke CSV saat itu juga, jadi data yang sudah
terkumpul tetap utuh kalau uji dihentikan atau device mati di tengah jalan.
"""

import sys, os, time, json, signal, argparse
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

STATUS_FILE  = "/tmp/bench_t4_status.json"
RESULTS_FILE = "/root/logs/bench_t4_stability.json"
CSV_FILE     = "/root/logs/bench_t4_samples.csv"
STOP_FILE    = "/tmp/bench_t4_stop"

MIN_FPS_FLOOR   = 15.0   # FPS minimum yang harus dipertahankan
TARGET_FPS      = 20.0   # FPS target untuk skor penuh
THROTTLE_DROP   = 0.25   # FPS drop % yang dianggap throttle event
REPORT_INTERVAL = 60     # detik antar snapshot (default: per menit)
FPS_SMOOTH_WIN  = 5      # detik untuk smooth FPS

CSV_COLUMNS = [
    "elapsed_s", "timestamp", "fps", "lat_avg_ms", "lat_p50_ms", "lat_p95_ms",
    "lat_min_ms", "lat_max_ms", "temp_c", "ram_free_mb", "ram_used_mb",
    "load_1m", "frames_total", "throttle_events", "crash_events",
]

_running = True


def _sigterm(signum, frame):
    global _running
    _running = False


signal.signal(signal.SIGTERM, _sigterm)
signal.signal(signal.SIGINT,  _sigterm)


def _write_status(status: dict):
    try:
        with open(STATUS_FILE, "w") as f:
            json.dump(status, f)
    except Exception:
        pass


def _csv_init(path: str):
    """Start a fresh CSV with a header row. Returns False if it cannot be written."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(",".join(CSV_COLUMNS) + "\n")
        return True
    except Exception:
        return False


def _csv_append(path: str, snap: dict):
    """Append one sample. Flushed per row so a killed run keeps its data."""
    try:
        with open(path, "a") as f:
            f.write(",".join(str(snap.get(c, "")) for c in CSV_COLUMNS) + "\n")
            f.flush()
    except Exception:
        pass


def _percentile(sorted_vals: list, pct: float) -> float:
    """Nearest-rank percentile of an already-sorted list."""
    if not sorted_vals:
        return 0.0
    k = int(round((pct / 100.0) * (len(sorted_vals) - 1)))
    return sorted_vals[max(0, min(k, len(sorted_vals) - 1))]


def _loadavg() -> float:
    try:
        with open("/proc/loadavg") as f:
            return float(f.read().split()[0])
    except Exception:
        return 0.0


def _make_emit(cb=None):
    def emit(text="", tag="plain"):
        if cb:
            cb(text, tag)
        print(text, flush=True)
    return emit


def run(duration_s: float = 600, emit_cb=None,
        interval_s: float = REPORT_INTERVAL, csv_path: str = CSV_FILE) -> dict:
    global _running
    _running = True

    emit = _make_emit(emit_cb)

    interval_s = max(1.0, float(interval_s))
    fps_win    = min(FPS_SMOOTH_WIN, interval_s)   # jangan lebih kasar dari interval

    emit("═" * 64, "div")
    emit("T4  HARDWARE STABILITY (ENDURANCE & THERMAL)", "section")
    emit("═" * 64, "div")
    emit(f"  Duration          : {duration_s:.0f}s ({duration_s/3600:.2f}h)")
    emit(f"  Sample interval   : {interval_s:.0f}s (~{int(duration_s/interval_s)} titik)")
    emit(f"  CSV               : {csv_path}")
    emit(f"  FPS floor (pass)  : {MIN_FPS_FLOOR} fps")
    emit(f"  FPS target (full) : {TARGET_FPS} fps")
    emit(f"  Throttle threshold: FPS drop > {THROTTLE_DROP:.0%} from baseline")
    emit(f"  Stop file         : {STOP_FILE}")
    emit()

    # Remove stale stop file
    try:
        os.remove(STOP_FILE)
    except FileNotFoundError:
        pass

    # ── Import maix ───────────────────────────────────────────────────────────
    try:
        from maix import camera, nn, image as mi
        MAIX = True
    except ImportError:
        MAIX = False

    if not MAIX:
        emit("  ✗ maix not available — cannot run T4", "err")
        return {"test": "T4_Stability", "passed": False, "score": 0,
                "error": "maix not available"}

    try:
        from config import cfg
        from utils.health import _thermals, _meminfo
        from utils.nn_compat import load_detector
    except Exception as e:
        emit(f"  ✗ Import error: {e}", "err")
        return {"test": "T4_Stability", "passed": False, "score": 0, "error": str(e)}

    # ── Init ──────────────────────────────────────────────────────────────────
    try:
        detector, det_name = load_detector(cfg.MODEL_PATH)
        cam      = camera.Camera(cfg.INPUT_WIDTH, cfg.INPUT_HEIGHT, mi.Format.FMT_RGB888)
        cam.open()
        emit(f"  Camera + {det_name} ready", "ok")
    except Exception as e:
        emit(f"  ✗ Hardware init failed: {e}", "err")
        return {"test": "T4_Stability", "passed": False, "score": 0, "error": str(e)}

    csv_ok = _csv_init(csv_path)
    if not csv_ok:
        emit(f"  ⚠ CSV tidak bisa ditulis ({csv_path}) — lanjut tanpa CSV", "warn")

    # ── State ─────────────────────────────────────────────────────────────────
    start_time      = time.time()
    frames_total    = 0
    crash_events    = 0
    throttle_events = 0

    fps_window: list = []
    lat_window: list = []      # latensi per frame (ms) dalam interval berjalan
    fps_smooth       = 0.0
    baseline_fps     = None
    last_fps_t       = time.time()
    last_report_t    = -1.0    # index interval yang sudah dilaporkan

    snapshots: list  = []      # satu record per interval
    min_fps_seen     = float("inf")
    max_temp_seen    = 0.0

    status = {
        "running":         True,
        "elapsed_s":       0,
        "fps":             0.0,
        "temp_c":          0.0,
        "ram_free_mb":     0,
        "throttle_events": 0,
        "crash_events":    0,
        "frames_total":    0,
        "start_time":      time.strftime("%Y-%m-%dT%H:%M:%S"),
        "target_s":        duration_s,
        "interval_s":      interval_s,
        "csv":             csv_path if csv_ok else None,
        "detector":        det_name,
    }
    _write_status(status)

    emit(f"  Warming up 30s for baseline FPS...")

    # ── Main loop ─────────────────────────────────────────────────────────────
    while _running and not os.path.exists(STOP_FILE):
        elapsed = time.time() - start_time
        if elapsed >= duration_s:
            break

        # ── One pipeline iteration ────────────────────────────────────────────
        try:
            t0  = time.perf_counter()
            f   = cam.read()
            detector.detect(f, conf_th=cfg.CONF_THRESHOLD, iou_th=cfg.IOU_THRESHOLD)
            f.to_jpeg()
            frame_s   = max(time.perf_counter() - t0, 1e-6)
            frame_fps = 1.0 / frame_s
            fps_window.append(frame_fps)
            lat_window.append(frame_s * 1000.0)
            frames_total += 1
        except Exception as e:
            crash_events += 1
            emit(f"  ⚠ Frame error ({e}) — continuing", "warn")
            # Attempt camera recovery
            try:
                cam.close()
                time.sleep(0.5)
                cam.open()
            except Exception:
                pass
            time.sleep(0.1)
            continue

        # ── FPS smoothing (every fps_win seconds) ─────────────────────────────
        now = time.time()
        if now - last_fps_t >= fps_win:
            fps_smooth   = sum(fps_window) / len(fps_window) if fps_window else 0
            fps_window   = []
            last_fps_t   = now
            min_fps_seen = min(min_fps_seen, fps_smooth)

            # Establish baseline after 30s warm-up
            if baseline_fps is None and elapsed >= 30:
                baseline_fps = fps_smooth
                emit(f"  Baseline FPS established: {baseline_fps:.1f}", "ok")

            # Throttle detection
            if baseline_fps and fps_smooth < baseline_fps * (1 - THROTTLE_DROP):
                throttle_events += 1
                emit(f"  ⚠ Throttle event #{throttle_events}: "
                     f"fps={fps_smooth:.1f} (base={baseline_fps:.1f})", "warn")

        # ── Snapshot per interval ─────────────────────────────────────────────
        bucket = int(elapsed // interval_s)
        if bucket > last_report_t:
            last_report_t = bucket

            thermals  = _thermals()
            temp      = max(thermals.values()) if thermals else 0.0
            mem       = _meminfo()
            ram_free  = mem.get("MemAvailable", 0) // 1024
            ram_used  = (mem.get("MemTotal", 0) - mem.get("MemAvailable", 0)) // 1024
            max_temp_seen = max(max_temp_seen, temp)

            lat_sorted = sorted(lat_window)
            lat_window = []
            lat_avg    = (sum(lat_sorted) / len(lat_sorted)) if lat_sorted else 0.0

            snap = {
                "elapsed_s":       int(elapsed),
                "timestamp":       time.strftime("%Y-%m-%dT%H:%M:%S"),
                "fps":             round(fps_smooth, 2),
                "lat_avg_ms":      round(lat_avg, 2),
                "lat_p50_ms":      round(_percentile(lat_sorted, 50), 2),
                "lat_p95_ms":      round(_percentile(lat_sorted, 95), 2),
                "lat_min_ms":      round(lat_sorted[0], 2) if lat_sorted else 0.0,
                "lat_max_ms":      round(lat_sorted[-1], 2) if lat_sorted else 0.0,
                "temp_c":          temp,
                "ram_free_mb":     ram_free,
                "ram_used_mb":     ram_used,
                "load_1m":         _loadavg(),
                "frames_total":    frames_total,
                "throttle_events": throttle_events,
                "crash_events":    crash_events,
            }
            snapshots.append(snap)
            if csv_ok:
                _csv_append(csv_path, snap)

            elapsed_str = f"{int(elapsed)//3600:02d}:{(int(elapsed)%3600)//60:02d}:{int(elapsed)%60:02d}"
            emit(f"  [{elapsed_str}]  "
                 f"FPS={fps_smooth:5.1f}  "
                 f"lat p50={snap['lat_p50_ms']:6.1f}ms p95={snap['lat_p95_ms']:6.1f}ms  "
                 f"T={temp:4.1f}°C  "
                 f"RAM={ram_free}MB  "
                 f"throttle={throttle_events}  "
                 f"crash={crash_events}")

            status.update(snap)
            status["running"] = True
            _write_status(status)

    # ── Done ──────────────────────────────────────────────────────────────────
    try:
        cam.close()
    except Exception:
        pass

    actual_duration = time.time() - start_time
    completed       = (actual_duration >= duration_s * 0.99) or (not _running)

    lat_all_p50 = round(sum(s["lat_p50_ms"] for s in snapshots) / len(snapshots), 2) if snapshots else None
    lat_all_p95 = max((s["lat_p95_ms"] for s in snapshots), default=None)

    emit()
    emit(f"  Total frames    : {frames_total}")
    emit(f"  Actual duration : {actual_duration:.0f}s")
    emit(f"  Samples (CSV)   : {len(snapshots)}")
    emit(f"  Throttle events : {throttle_events}")
    emit(f"  Crash events    : {crash_events}")
    emit(f"  Min FPS seen    : {min_fps_seen:.1f}")
    emit(f"  Max temp        : {max_temp_seen:.1f}°C")
    emit(f"  Latency p50/p95 : {lat_all_p50} / {lat_all_p95} ms")
    emit(f"  Baseline FPS    : {baseline_fps:.1f}" if baseline_fps else "  Baseline FPS    : N/A")

    # ── Score ─────────────────────────────────────────────────────────────────
    fps_for_score = fps_smooth if fps_smooth > 0 else (min_fps_seen if min_fps_seen < float("inf") else 0)

    if crash_events == 0:
        score_base = 50
    else:
        score_base = max(0, 50 - crash_events * 15)

    fps_ratio  = min(fps_for_score / TARGET_FPS, 1.0) if fps_for_score > 0 else 0
    score_fps  = round(50 * fps_ratio)
    score_throt = max(0, min(10, throttle_events)) * 2   # up to -20 penalty
    score = max(0, score_base + score_fps - score_throt)

    # Pass criteria
    passed_fps   = (min_fps_seen >= MIN_FPS_FLOOR) if min_fps_seen < float("inf") else False
    passed_crash = (crash_events == 0)
    passed       = passed_fps and passed_crash

    tag   = "ok" if passed else "err"
    emoji = "✓" if passed else "✗"
    emit()
    emit(f"  FPS floor ({MIN_FPS_FLOOR} fps): {'PASS' if passed_fps else 'FAIL'}  "
         f"(min={min_fps_seen:.1f})", "ok" if passed_fps else "err")
    emit(f"  Zero crash       : {'PASS' if passed_crash else f'FAIL ({crash_events} events)'}",
         "ok" if passed_crash else "err")
    emit(f"  {emoji} Overall: {'PASS' if passed else 'FAIL'}", tag)
    emit(f"  Score: {score}/100")

    results = {
        "test":            "T4_Stability",
        "passed":          passed,
        "score":           score,
        "duration_s":      round(actual_duration, 1),
        "target_s":        duration_s,
        "interval_s":      interval_s,
        "csv":             csv_path if csv_ok else None,
        "detector":        det_name,
        "frames_total":    frames_total,
        "baseline_fps":    round(baseline_fps, 1) if baseline_fps else None,
        "min_fps":         round(min_fps_seen, 1) if min_fps_seen < float("inf") else None,
        "avg_fps_final":   round(fps_smooth, 1),
        "max_temp_c":      round(max_temp_seen, 1),
        "lat_p50_ms":      lat_all_p50,
        "lat_p95_max_ms":  lat_all_p95,
        "throttle_events": throttle_events,
        "crash_events":    crash_events,
        "snapshots":       snapshots,
        "min_fps_floor":   MIN_FPS_FLOOR,
        "timestamp":       time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    status["running"] = False
    _write_status(status)

    try:
        os.remove(STOP_FILE)
    except FileNotFoundError:
        pass

    _save(results)
    return results


def _save(results: dict):
    os.makedirs(os.path.dirname(RESULTS_FILE), exist_ok=True)
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="T4 Stability Test")
    parser.add_argument("--duration", type=float, default=600,
                        help="Test duration in seconds (default 600 = 10 min)")
    parser.add_argument("--interval", type=float, default=REPORT_INTERVAL,
                        help="Sampling interval in seconds (default 60)")
    parser.add_argument("--csv", default=CSV_FILE,
                        help=f"CSV output path (default {CSV_FILE})")
    args = parser.parse_args()
    run(duration_s=args.duration, interval_s=args.interval, csv_path=args.csv)

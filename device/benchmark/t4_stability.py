#!/usr/bin/env python3
"""
Test 4 — Hardware Stability (Endurance & Thermal)
===================================================
Menjalankan full pipeline (cam → NPU → JPEG) dalam durasi tertentu
dan merekam metrik per menit:
  - FPS rata-rata per interval
  - Suhu CPU/NPU
  - RAM tersedia
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
"""

import sys, os, time, json, signal, argparse
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

STATUS_FILE  = "/tmp/bench_t4_status.json"
RESULTS_FILE = "/root/logs/bench_t4_stability.json"
STOP_FILE    = "/tmp/bench_t4_stop"

MIN_FPS_FLOOR   = 15.0   # FPS minimum yang harus dipertahankan
TARGET_FPS      = 20.0   # FPS target untuk skor penuh
THROTTLE_DROP   = 0.25   # FPS drop % yang dianggap throttle event
REPORT_INTERVAL = 60     # detik antar snapshot per-menit
FPS_SMOOTH_WIN  = 5      # detik untuk smooth FPS

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


def _make_emit(cb=None):
    def emit(text="", tag="plain"):
        if cb:
            cb(text, tag)
        print(text, flush=True)
    return emit


def run(duration_s: float = 600, emit_cb=None) -> dict:
    global _running
    _running = True

    emit = _make_emit(emit_cb)

    emit("═" * 64, "div")
    emit("T4  HARDWARE STABILITY (ENDURANCE & THERMAL)", "section")
    emit("═" * 64, "div")
    emit(f"  Duration          : {duration_s:.0f}s ({duration_s/3600:.2f}h)")
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
    except Exception as e:
        emit(f"  ✗ Import error: {e}", "err")
        return {"test": "T4_Stability", "passed": False, "score": 0, "error": str(e)}

    # ── Init ──────────────────────────────────────────────────────────────────
    try:
        detector = nn.YOLO11(model=cfg.MODEL_PATH)
        cam      = camera.Camera(cfg.INPUT_WIDTH, cfg.INPUT_HEIGHT, mi.Format.FMT_RGB888)
        cam.open()
        emit(f"  Camera + YOLO11 ready", "ok")
    except Exception as e:
        emit(f"  ✗ Hardware init failed: {e}", "err")
        return {"test": "T4_Stability", "passed": False, "score": 0, "error": str(e)}

    # ── State ─────────────────────────────────────────────────────────────────
    start_time      = time.time()
    frames_total    = 0
    crash_events    = 0
    throttle_events = 0

    fps_window: list = []
    fps_smooth       = 0.0
    baseline_fps     = None
    last_fps_t       = time.time()
    last_report_t    = -1.0    # track per-minute snapshots

    snapshots: list  = []      # per-minute records
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
            frame_fps = 1.0 / max(time.perf_counter() - t0, 1e-6)
            fps_window.append(frame_fps)
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

        # ── FPS smoothing (every FPS_SMOOTH_WIN seconds) ───────────────────────
        now = time.time()
        if now - last_fps_t >= FPS_SMOOTH_WIN:
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

        # ── Per-minute snapshot ───────────────────────────────────────────────
        minute = int(elapsed) // REPORT_INTERVAL
        if minute > last_report_t:
            last_report_t = minute

            thermals  = _thermals()
            temp      = max(thermals.values()) if thermals else 0.0
            mem       = _meminfo()
            ram_free  = mem.get("MemAvailable", 0) // 1024
            max_temp_seen = max(max_temp_seen, temp)

            snap = {
                "elapsed_s":       int(elapsed),
                "fps":             round(fps_smooth, 1),
                "temp_c":          temp,
                "ram_free_mb":     ram_free,
                "throttle_events": throttle_events,
                "crash_events":    crash_events,
                "frames_total":    frames_total,
            }
            snapshots.append(snap)

            elapsed_str = f"{int(elapsed)//3600:02d}:{(int(elapsed)%3600)//60:02d}:{int(elapsed)%60:02d}"
            emit(f"  [{elapsed_str}]  "
                 f"FPS={fps_smooth:5.1f}  "
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

    emit()
    emit(f"  Total frames    : {frames_total}")
    emit(f"  Actual duration : {actual_duration:.0f}s")
    emit(f"  Throttle events : {throttle_events}")
    emit(f"  Crash events    : {crash_events}")
    emit(f"  Min FPS seen    : {min_fps_seen:.1f}")
    emit(f"  Max temp        : {max_temp_seen:.1f}°C")
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
        "frames_total":    frames_total,
        "baseline_fps":    round(baseline_fps, 1) if baseline_fps else None,
        "min_fps":         round(min_fps_seen, 1) if min_fps_seen < float("inf") else None,
        "avg_fps_final":   round(fps_smooth, 1),
        "max_temp_c":      round(max_temp_seen, 1),
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
    args = parser.parse_args()
    run(duration_s=args.duration)

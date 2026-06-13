#!/usr/bin/env python3
"""
AuralAI Long-Term Stress Test v1
=================================
Schedule : 3 jam/hari × 5 hari = 15 jam total
Pipeline : Camera → YOLO → Annotate → JPEG encode (full AuralAI Explorer loop)

State disimpan ke long_term_state.json → resume otomatis jika diinterupsi.
Log per hari ke logs/day_NN_YYYY-MM-DD.csv (15-menit interval).

Usage:
  python long_term_stress.py            # Jalankan / lanjutkan dari titik terakhir
  python long_term_stress.py --report   # Tampilkan laporan semua hari
  python long_term_stress.py --reset    # Reset state (mulai dari Hari 1)
  python long_term_stress.py --day N    # Paksa jalankan hari N (1-5)
"""

import os, sys, time, json, csv, gc, math, argparse
from datetime import datetime

try:
    from maix import camera, image, nn, app
    MAIX_OK = True
except ImportError as e:
    print(f"[WARN] maix import: {e}")
    MAIX_OK = False

# ─────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────
TOTAL_DAYS       = 5
HOURS_PER_DAY    = 3
SECONDS_PER_DAY  = HOURS_PER_DAY * 3600   # 10800 detik
LOG_INTERVAL_S   = 900                     # checkpoint tiap 15 menit

_DIR           = os.path.dirname(os.path.abspath(__file__))
CHECKPOINT_FILE = os.path.join(_DIR, "long_term_state.json")
LOG_DIR        = os.path.join(_DIR, "logs")

DIV  = "=" * 62
DIV2 = "-" * 62


# ─────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────
def ts():      return time.time()
def now_str(): return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def pr(label, val=""):
    if val: print(f"  {label:<42} {val}")
    else:   print(f"  {label}")

def psec(title):
    print(); print(DIV); print(f"  {title}"); print(DIV)

def read_file(path):
    try:
        with open(path) as f: return f.read().strip()
    except: return None

def read_temps():
    zones = []
    base = "/sys/class/thermal"
    if not os.path.exists(base): return zones
    for entry in sorted(os.listdir(base)):
        if not entry.startswith("thermal_zone"): continue
        t_raw  = read_file(f"{base}/{entry}/temp")
        t_type = read_file(f"{base}/{entry}/type") or "?"
        if t_raw:
            try:
                val = int(t_raw)
                c   = val / 1000.0 if val > 1000 else float(val)
                zones.append((entry, t_type, c))
            except: pass
    return zones

def mem_free_mb():
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                p = line.split()
                if p[0].rstrip(":") == "MemFree":
                    return int(p[1]) // 1024
    except: pass
    return 0

def find_yolo_model():
    candidates = [
        ("/root/models/yolo11n.mud", "YOLO11n"),
        ("/root/models/yolov8n.mud", "YOLOv8n"),
        ("/root/models/yolov5s.mud", "YOLOv5s"),
    ]
    for path, label in candidates:
        if os.path.exists(path):
            return path, label
    return None, None


# ─────────────────────────────────────────────────────────
# STATE MANAGEMENT
# ─────────────────────────────────────────────────────────
def load_state():
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE) as f:
                return json.load(f)
        except: pass
    return {
        "current_day":     1,
        "days_completed":  [],
        "total_frames":    0,
        "start_date":      None,
        "last_updated":    None,
    }

def save_state(state):
    state["last_updated"] = now_str()
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(state, f, indent=2)


# ─────────────────────────────────────────────────────────
# CSV LOGGING
# ─────────────────────────────────────────────────────────
def init_csv(day_num):
    os.makedirs(LOG_DIR, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(LOG_DIR, f"day_{day_num:02d}_{date_str}.csv")
    if not os.path.exists(path):
        with open(path, "w", newline="") as f:
            csv.writer(f).writerow([
                "timestamp", "elapsed_s", "window_fps", "cumulative_fps",
                "frames_total", "ram_free_mb",
                "temp_cpu_c", "temp_zone0_c", "temp_zone1_c",
                "throttle_detected",
            ])
    return path

def append_csv(path, row):
    with open(path, "a", newline="") as f:
        csv.writer(f).writerow(row)


# ─────────────────────────────────────────────────────────
# CHECKPOINT PRINTER
# ─────────────────────────────────────────────────────────
def print_checkpoint(day_num, elapsed, window_fps, total_fps,
                     frame_count, mem_mb, temps, throttle, prev_fps):
    h = int(elapsed // 3600)
    m = int((elapsed % 3600) // 60)
    temp_str = "  ".join(f"{zt}={c:.0f}°C" for _, zt, c in temps) or "no sysfs"
    throttle_tag = "  ⚠ THROTTLE" if throttle else ""

    print(
        f"  [Day {day_num} | {h:02d}:{m:02d}]  "
        f"win={window_fps:.1f}fps  avg={total_fps:.1f}fps  "
        f"frames={frame_count:,}  RAM={mem_mb}MB  {temp_str}{throttle_tag}"
    )


# ─────────────────────────────────────────────────────────
# DAILY RUN — full pipeline
# ─────────────────────────────────────────────────────────
def run_day_full_pipeline(day_num, state, csv_path):
    model_path, model_label = find_yolo_model()
    if not model_path:
        pr("WARN: YOLO model tidak ditemukan — fallback camera-only")
        return run_day_camera_only(day_num, state, csv_path)

    pr("Model", f"{model_label} ({model_path})")
    try:
        if   "yolo11" in model_path: detector = nn.YOLO11(model=model_path, dual_buff=True)
        elif "yolov8" in model_path: detector = nn.YOLOv8(model=model_path, dual_buff=True)
        else:                        detector = nn.YOLOv5(model=model_path, dual_buff=True)

        cam = camera.Camera(
            detector.input_width(), detector.input_height(), detector.input_format()
        )
        for _ in range(10):             # warmup
            img = cam.read()
            _ = detector.detect(img)
    except Exception as ex:
        pr("ERROR init", str(ex)); return {}

    frame_count   = 0
    window_frames = 0
    fps_log       = []
    max_temps     = {}
    prev_fps      = None
    throttle_events = 0

    t_start      = ts()
    t_end        = ts() + SECONDS_PER_DAY
    t_log        = ts() + LOG_INTERVAL_S
    window_start = ts()

    pr(""); pr(f"Loop hari {day_num} dimulai — target {HOURS_PER_DAY}h...")

    while ts() < t_end:
        img  = cam.read()
        objs = detector.detect(img, conf_th=0.5, iou_th=0.45)
        for obj in objs:
            img.draw_rect(obj.x, obj.y, obj.w, obj.h,
                          image.Color.from_rgb(255, 0, 0))
        _ = img.to_format(image.Format.FMT_JPEG)

        frame_count   += 1
        window_frames += 1

        if ts() >= t_log:
            elapsed    = ts() - t_start
            window_s   = ts() - window_start
            window_fps = window_frames / window_s if window_s > 0 else 0
            total_fps  = frame_count   / elapsed  if elapsed  > 0 else 0
            mem_mb     = mem_free_mb()

            temps    = read_temps()
            temps_c  = [c for _, _, c in temps]
            temp_cpu = next((c for _, zt, c in temps if "cpu" in zt.lower()), None)
            t0 = temps_c[0] if len(temps_c) > 0 else None
            t1 = temps_c[1] if len(temps_c) > 1 else None

            throttle = (prev_fps is not None and prev_fps > 0
                        and (prev_fps - window_fps) / prev_fps > 0.10)
            if throttle:
                throttle_events += 1

            fps_log.append((elapsed, window_fps))
            for zn, _, c in temps:
                if zn not in max_temps or c > max_temps[zn]:
                    max_temps[zn] = c

            append_csv(csv_path, [
                now_str(), f"{elapsed:.0f}", f"{window_fps:.2f}", f"{total_fps:.2f}",
                frame_count, mem_mb,
                f"{temp_cpu:.1f}" if temp_cpu else "",
                f"{t0:.1f}"       if t0        else "",
                f"{t1:.1f}"       if t1        else "",
                "Y" if throttle else "N",
            ])

            print_checkpoint(day_num, elapsed, window_fps, total_fps,
                             frame_count, mem_mb, temps, throttle, prev_fps)

            state["total_frames"] += window_frames
            save_state(state)

            prev_fps      = window_fps
            t_log         = ts() + LOG_INTERVAL_S
            window_start  = ts()
            window_frames = 0

        if MAIX_OK and hasattr(app, "need_exit") and app.need_exit():
            pr("App exit requested — berhenti lebih awal"); break

    total_elapsed = ts() - t_start
    del cam, detector
    gc.collect()

    return _build_summary(day_num, total_elapsed, frame_count,
                          fps_log, throttle_events, max_temps, csv_path)


# ─────────────────────────────────────────────────────────
# DAILY RUN — camera-only (tanpa YOLO)
# ─────────────────────────────────────────────────────────
def run_day_camera_only(day_num, state, csv_path):
    try:
        cam = camera.Camera(320, 240)
    except Exception as ex:
        pr("Camera error", str(ex))
        return run_day_cpu_fallback(day_num, state, csv_path)

    frame_count = 0; window_frames = 0; fps_log = []; max_temps = {}
    t_start = ts(); t_end = ts() + SECONDS_PER_DAY
    t_log = ts() + LOG_INTERVAL_S; window_start = ts()

    pr("Camera-only mode (320×240 + JPEG)")

    while ts() < t_end:
        img = cam.read()
        _ = img.to_format(image.Format.FMT_JPEG)
        frame_count += 1; window_frames += 1

        if ts() >= t_log:
            elapsed   = ts() - t_start
            window_s  = ts() - window_start
            window_fps= window_frames / window_s if window_s > 0 else 0
            total_fps = frame_count / elapsed if elapsed > 0 else 0
            mem_mb    = mem_free_mb()
            temps     = read_temps()
            for zn, _, c in temps:
                if zn not in max_temps or c > max_temps[zn]: max_temps[zn] = c
            append_csv(csv_path, [
                now_str(), f"{elapsed:.0f}", f"{window_fps:.2f}", f"{total_fps:.2f}",
                frame_count, mem_mb, "", "", "", "N",
            ])
            print_checkpoint(day_num, elapsed, window_fps, total_fps,
                             frame_count, mem_mb, temps, False, None)
            fps_log.append((elapsed, window_fps))
            state["total_frames"] += window_frames; save_state(state)
            t_log = ts() + LOG_INTERVAL_S; window_start = ts(); window_frames = 0

    del cam
    total_elapsed = ts() - t_start
    return _build_summary(day_num, total_elapsed, frame_count,
                          fps_log, 0, max_temps, csv_path)


# ─────────────────────────────────────────────────────────
# DAILY RUN — CPU-only fallback (tanpa maix)
# ─────────────────────────────────────────────────────────
def run_day_cpu_fallback(day_num, state, csv_path):
    pr("CPU-only burn (sin/cos loop) — maix tidak tersedia")
    frame_count = 0; window_frames = 0; fps_log = []; max_temps = {}
    t_start = ts(); t_end = ts() + SECONDS_PER_DAY
    t_log = ts() + LOG_INTERVAL_S; window_start = ts()

    while ts() < t_end:
        acc = 0.0
        for i in range(1, 2001):
            acc += math.sin(i * 0.01) * math.cos(i * 0.02)
        frame_count += 1; window_frames += 1

        if ts() >= t_log:
            elapsed   = ts() - t_start
            window_s  = ts() - window_start
            window_fps= window_frames / window_s if window_s > 0 else 0
            temps     = read_temps()
            temps_c   = [c for _, _, c in temps]
            for zn, _, c in temps:
                if zn not in max_temps or c > max_temps[zn]: max_temps[zn] = c
            append_csv(csv_path, [
                now_str(), f"{elapsed:.0f}", f"{window_fps:.2f}", "",
                frame_count, mem_free_mb(),
                "", temps_c[0] if temps_c else "", "", "N",
            ])
            print_checkpoint(day_num, elapsed, window_fps, window_fps,
                             frame_count, mem_free_mb(), temps, False, None)
            fps_log.append((elapsed, window_fps))
            state["total_frames"] += window_frames; save_state(state)
            t_log = ts() + LOG_INTERVAL_S; window_start = ts(); window_frames = 0

    return _build_summary(day_num, ts() - t_start, frame_count,
                          fps_log, 0, max_temps, csv_path)


# ─────────────────────────────────────────────────────────
# SUMMARY BUILDER
# ─────────────────────────────────────────────────────────
def _build_summary(day_num, duration_s, total_frames,
                   fps_log, throttle_events, max_temps, csv_path):
    avg_fps   = total_frames / duration_s if duration_s > 0 else 0
    fps_first = fps_log[0][1]  if fps_log else None
    fps_last  = fps_log[-1][1] if fps_log else None

    print(); print(DIV2)
    pr(f"DAY {day_num} SELESAI")
    pr("Durasi",          f"{duration_s/3600:.2f} jam  ({duration_s:.0f}s)")
    pr("Total frame",     f"{total_frames:,}")
    pr("Avg FPS",         f"{avg_fps:.2f}")
    if fps_first is not None and fps_last is not None:
        pr("FPS drift",   f"{fps_first:.1f} → {fps_last:.1f}  (Δ{fps_last-fps_first:+.1f})")
    pr("Throttle events", str(throttle_events))
    if max_temps:
        pr("Peak temps",  "  ".join(f"[{zn}]={c:.1f}°C" for zn, c in max_temps.items()))
    pr("Log CSV",         csv_path)

    return {
        "day":             day_num,
        "date":            datetime.now().strftime("%Y-%m-%d"),
        "duration_s":      duration_s,
        "total_frames":    total_frames,
        "avg_fps":         avg_fps,
        "fps_first":       fps_first,
        "fps_last":        fps_last,
        "throttle_events": throttle_events,
        "max_temps":       max_temps,
        "csv_path":        csv_path,
    }


# ─────────────────────────────────────────────────────────
# RUN DAY  (dispatcher)
# ─────────────────────────────────────────────────────────
def run_day(day_num, state):
    psec(f"DAY {day_num}/{TOTAL_DAYS} — {now_str()}")
    pr("Target", f"{HOURS_PER_DAY} jam ({SECONDS_PER_DAY}s)")

    csv_path = init_csv(day_num)
    pr("CSV log", csv_path)

    if not MAIX_OK:
        return run_day_cpu_fallback(day_num, state, csv_path)

    return run_day_full_pipeline(day_num, state, csv_path)


# ─────────────────────────────────────────────────────────
# FINAL REPORT
# ─────────────────────────────────────────────────────────
def print_report(state):
    psec("LAPORAN AKHIR — AuralAI Long-Term Stress Test")

    days = state.get("days_completed", [])
    if not days:
        pr("Belum ada hari yang selesai."); return

    total_hours    = sum(d.get("duration_s", 0) for d in days) / 3600
    total_frames   = sum(d.get("total_frames", 0) for d in days)
    avg_fps_all    = sum(d.get("avg_fps", 0) for d in days) / len(days)
    total_throttle = sum(d.get("throttle_events", 0) for d in days)

    pr("Hari selesai",     f"{len(days)}/{TOTAL_DAYS}")
    pr("Total durasi",     f"{total_hours:.2f} jam")
    pr("Total frame",      f"{total_frames:,}")
    pr("Rata-rata FPS",    f"{avg_fps_all:.2f} fps")
    pr("Total throttle",   str(total_throttle))

    print(); pr("Per-Hari Breakdown:")
    header = f"  {'Day':<6}  {'Tanggal':<12}  {'FPS avg':<9}  {'Frames':<10}  {'Throttle':<9}  {'FPS drift'}"
    print(header); print("  " + "-" * 65)
    for d in days:
        drift = ""
        if d.get("fps_first") is not None and d.get("fps_last") is not None:
            delta = d["fps_last"] - d["fps_first"]
            drift = f"{delta:+.1f}"
        print(f"  Day {d['day']:<3}  {d.get('date','?'):<12}  "
              f"{d.get('avg_fps',0):<9.1f}  {d.get('total_frames',0):<10,}  "
              f"{d.get('throttle_events',0):<9}  {drift}")

    print(); pr("Peak Temperatures per Hari:")
    for d in days:
        temps = d.get("max_temps", {})
        temp_str = "  ".join(f"[{zn}]={c:.1f}°C" for zn, c in temps.items()) if temps else "N/A"
        pr(f"  Day {d['day']}", temp_str)

    print(); print(DIV2)
    if total_throttle == 0:
        pr("Verdict", "✓ STABIL — tidak ada thermal throttle selama 5 hari")
    elif total_throttle <= 5:
        pr("Verdict", f"⚠ SEMI-STABIL — {total_throttle} throttle event (pertimbangkan cooling)")
    else:
        pr("Verdict", f"✗ TIDAK STABIL — {total_throttle} throttle event! Wajib heatsink/cooling")

    print(DIV)


# ─────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="AuralAI Long-Term Stress Test")
    parser.add_argument("--report", action="store_true",
                        help="Tampilkan laporan tanpa menjalankan tes")
    parser.add_argument("--reset",  action="store_true",
                        help="Reset state — mulai dari Hari 1")
    parser.add_argument("--day",    type=int, metavar="N",
                        help="Paksa jalankan hari N (1-5)")
    args = parser.parse_args()

    if args.reset:
        if os.path.exists(CHECKPOINT_FILE):
            os.remove(CHECKPOINT_FILE)
        print("State di-reset. Jalankan ulang untuk memulai Hari 1.")
        return

    state = load_state()

    if args.report:
        print_report(state); return

    if state["start_date"] is None:
        state["start_date"] = now_str()

    psec("AuralAI Long-Term Stress Test v1")
    pr("Schedule",    f"{HOURS_PER_DAY} jam/hari × {TOTAL_DAYS} hari = {HOURS_PER_DAY*TOTAL_DAYS} jam total")
    pr("State file",  CHECKPOINT_FILE)
    pr("Log dir",     LOG_DIR)
    pr("Sudah selesai", f"{len(state['days_completed'])}/{TOTAL_DAYS} hari")
    pr("Hari berikutnya", f"Day {state['current_day']}")
    pr("MaixPy",      "Available" if MAIX_OK else "NOT FOUND — CPU fallback")

    day_to_run = args.day if args.day else state["current_day"]

    if day_to_run > TOTAL_DAYS:
        pr(""); pr("Semua hari sudah selesai!")
        print_report(state); return

    if day_to_run < 1 or day_to_run > TOTAL_DAYS:
        pr("ERROR", f"--day harus antara 1 dan {TOTAL_DAYS}"); return

    summary = run_day(day_to_run, state)

    if summary:
        # Upsert: jika re-run hari yang sama, timpa
        state["days_completed"] = [
            d for d in state["days_completed"] if d["day"] != day_to_run
        ]
        state["days_completed"].append(summary)
        state["days_completed"].sort(key=lambda d: d["day"])
        state["current_day"] = day_to_run + 1
        save_state(state)

        print()
        if day_to_run >= TOTAL_DAYS:
            pr("Semua hari selesai!")
            print_report(state)
        else:
            remaining = TOTAL_DAYS - day_to_run
            pr(f"Hari {day_to_run} selesai.")
            pr(f"Sisa", f"{remaining} hari lagi")
            pr("Besok", f"jalankan ulang script untuk Day {day_to_run + 1}")


if __name__ == "__main__":
    main()

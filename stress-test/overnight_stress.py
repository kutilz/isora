#!/usr/bin/env python3
"""
AuralAI Overnight Stress Test v1
==================================
Dirancang untuk berjalan tanpa pengawasan selama 8 jam.
Sepenuhnya mandiri — tidak butuh companion PC.
Aman untuk SSH disconnect.

Pola Duty Cycle (realistis — bukan 100% full load):
  ┌──────────────────┬─────────────┐
  │  ACTIVE  (15 min)│ STANDBY (2m)│ ... (ulang)
  │ Cam+NPU+JPEG     │ NPU idle    │
  └──────────────────┴─────────────┘
  Jika suhu tinggi → COOLDOWN override sampai temp < TEMP_SAFE_C

Watchdogs:
  • Thermal  — warning@65°C, reduce@70°C, emergency standby@75°C
  • Memory   — GC tiap 5 menit, shutdown darurat jika RAM < 20MB
  • Heartbeat— tulis status JSON tiap 60 detik (bisa dimonitor tanpa tailing log)

Persistent Logging:
  • Log text   : stress-test/logs/overnight_YYYYMMDD_HHMMSS.log
  • CSV metric  : stress-test/logs/overnight_YYYYMMDD_HHMMSS.csv
  • Status JSON : /tmp/overnight_status.json  (atomic update tiap menit)
  • PID file    : /tmp/overnight_stress.pid

Cara Menjalankan:
  # Dengan screen (direkomendasikan — bisa di-attach ulang):
  screen -S overnight
  python overnight_stress.py
  # Ctrl+A D untuk detach, screen -r overnight untuk attach ulang

  # Dengan nohup (true background):
  nohup python overnight_stress.py &
  tail -f stress-test/logs/overnight_*.log

  # Stop gracefully (simpan laporan sebelum keluar):
  kill -TERM $(cat /tmp/overnight_stress.pid)

  # Lihat status live:
  cat /tmp/overnight_status.json

Arguments:
  --duration HOURS   Durasi total (default: 8)
  --active-min MIN   Fase active dalam menit (default: 15)
  --standby-min MIN  Fase standby dalam menit (default: 2)
  --dry-run          Jalankan tanpa kamera/NPU (CPU burn), untuk test watchdog
"""

import os, sys, gc, time, json, csv, math, signal, threading, argparse
from datetime import datetime

try:
    from maix import camera, image, nn, app
    MAIX_OK = True
except ImportError as e:
    print(f"[WARN] maix: {e} — dry-run mode diaktifkan")
    MAIX_OK = False

# ─────────────────────────────────────────────────────────
# CONFIG (bisa di-override via argparse)
# ─────────────────────────────────────────────────────────
CFG = {
    "total_hours":    8,
    "active_min":     15,
    "standby_min":    2,
    "cooldown_min":   5,

    # Thermal thresholds (°C)
    "temp_warn":      65.0,   # log warning saja
    "temp_reduce":    70.0,   # kurangi framerate (skip-frame mode)
    "temp_emergency": 75.0,   # paksa COOLDOWN segera
    "temp_safe":      58.0,   # aman kembali ke ACTIVE

    # Memory thresholds (MB)
    "ram_gc_trigger": 50,     # trigger GC
    "ram_critical":   20,     # graceful shutdown

    # Intervals
    "gc_interval_s":        300,    # GC tiap 5 menit
    "heartbeat_s":           60,    # status JSON tiap 1 menit
    "watchdog_interval_s":    2,    # cek suhu tiap 2 detik

    # Storage
    "csv_rotate_mb":    10,
    "model_path":       None,       # auto-detect
}

_DIR     = os.path.dirname(os.path.abspath(__file__))
LOG_DIR  = os.path.join(_DIR, "logs")
PID_FILE = "/tmp/overnight_stress.pid"
STATUS_FILE = "/tmp/overnight_status.json"

# ─────────────────────────────────────────────────────────
# DUTY CYCLE STATES
# ─────────────────────────────────────────────────────────
STATE_ACTIVE   = "active"
STATE_STANDBY  = "standby"
STATE_COOLDOWN = "cooldown"   # thermal emergency override
STATE_GC_PAUSE = "gc_pause"   # brief GC pause


# ─────────────────────────────────────────────────────────
# DUAL LOGGER (file + stdout)
# ─────────────────────────────────────────────────────────
class DualLogger:
    def __init__(self, log_path):
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        # line buffering + explicit flush = survives crash/disconnect
        self._f = open(log_path, "a", buffering=1, encoding="utf-8")
        self._lock = threading.Lock()

    def _write(self, level, msg):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] [{level:<8}] {msg}"
        with self._lock:
            print(line, flush=True)
            self._f.write(line + "\n")
            self._f.flush()

    def info(self, m):  self._write("INFO",  m)
    def ok(self,   m):  self._write("OK",    m)
    def warn(self, m):  self._write("WARN",  m)
    def error(self, m): self._write("ERROR", m)
    def close(self):    self._f.close()


# ─────────────────────────────────────────────────────────
# PERSISTENT CSV (immediate flush, auto-rotate)
# ─────────────────────────────────────────────────────────
class PersistentCSV:
    HEADER = [
        "timestamp", "elapsed_s", "cycle_num", "duty_state",
        "window_fps", "cumulative_fps", "frames_total",
        "ram_free_mb", "gc_events",
        "temp_zone0_c", "temp_zone1_c", "temp_max_c",
        "thermal_events", "skip_frame_mode",
        "watchdog_note",
    ]

    def __init__(self, base_path, rotate_mb=10):
        self._base = base_path
        self._max_bytes = int(rotate_mb * 1024 * 1024)
        self._part = 0
        self._f = None
        self._writer = None
        self._open_new()

    def _open_new(self):
        if self._f:
            self._f.close()
        path = f"{self._base}_part{self._part}.csv"
        self._f = open(path, "a", buffering=1, newline="", encoding="utf-8")
        self._writer = csv.writer(self._f)
        if os.path.getsize(path) == 0:
            self._writer.writerow(self.HEADER)
        self._f.flush()

    def write(self, row: dict):
        self._writer.writerow([row.get(k, "") for k in self.HEADER])
        self._f.flush()
        if self._f.tell() > self._max_bytes:
            self._part += 1
            self._open_new()

    def close(self):
        if self._f: self._f.close()


# ─────────────────────────────────────────────────────────
# SYSTEM READERS
# ─────────────────────────────────────────────────────────
def read_file(path):
    try:
        with open(path) as f: return f.read().strip()
    except: return None

def read_temps():
    """Returns list of (zone_name, type_str, celsius)."""
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

def max_temp():
    temps = read_temps()
    return max((c for _, _, c in temps), default=0.0)

def mem_free_mb():
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                p = line.split()
                if p[0].rstrip(":") == "MemFree":
                    return int(p[1]) // 1024
    except: pass
    return 999  # unknown → assume OK

def find_yolo_model(override=None):
    if override and os.path.exists(override):
        return override
    for path in [
        "/root/models/yolo11n.mud",
        "/root/models/yolov8n.mud",
        "/root/models/yolov5s.mud",
    ]:
        if os.path.exists(path): return path
    return None


# ─────────────────────────────────────────────────────────
# THERMAL WATCHDOG (background thread)
# ─────────────────────────────────────────────────────────
class ThermalWatchdog(threading.Thread):
    def __init__(self, cfg, shared, log):
        super().__init__(daemon=True, name="ThermalWatchdog")
        self.cfg    = cfg
        self.shared = shared   # mutable dict shared across threads
        self.log    = log

    def run(self):
        while not self.shared.get("shutdown"):
            t = max_temp()
            self.shared["temp_max"] = t

            if t >= self.cfg["temp_emergency"]:
                if not self.shared.get("thermal_emergency"):
                    self.log.warn(f"THERMAL EMERGENCY: {t:.1f}°C ≥ {self.cfg['temp_emergency']}°C → force COOLDOWN")
                    self.shared["thermal_emergency"]  = True
                    self.shared["thermal_events"]    += 1
            elif t >= self.cfg["temp_reduce"]:
                if not self.shared.get("skip_frame_mode"):
                    self.log.warn(f"Thermal REDUCE: {t:.1f}°C → skip-frame mode aktif")
                    self.shared["skip_frame_mode"] = True
            elif t < self.cfg["temp_safe"]:
                if self.shared.get("thermal_emergency"):
                    self.log.ok(f"Thermal OK: {t:.1f}°C < {self.cfg['temp_safe']}°C → resume ACTIVE")
                    self.shared["thermal_emergency"] = False
                if self.shared.get("skip_frame_mode"):
                    self.log.ok(f"Thermal OK: skip-frame mode off")
                    self.shared["skip_frame_mode"] = False

            time.sleep(self.cfg["watchdog_interval_s"])


# ─────────────────────────────────────────────────────────
# MEMORY GUARDIAN (background thread)
# ─────────────────────────────────────────────────────────
class MemoryGuardian(threading.Thread):
    def __init__(self, cfg, shared, log):
        super().__init__(daemon=True, name="MemGuardian")
        self.cfg    = cfg
        self.shared = shared
        self.log    = log

    def run(self):
        while not self.shared.get("shutdown"):
            free_mb = mem_free_mb()
            self.shared["ram_free"] = free_mb

            if free_mb < self.cfg["ram_critical"]:
                self.log.error(f"MEMORY CRITICAL: {free_mb}MB free < {self.cfg['ram_critical']}MB → shutdown darurat!")
                self.shared["shutdown"] = True
                self.shared["shutdown_reason"] = f"OOM: only {free_mb}MB free"
                break

            if free_mb < self.cfg["ram_gc_trigger"]:
                self.log.warn(f"Memory low: {free_mb}MB — force GC")
                collected = gc.collect()
                self.shared["gc_events"] += 1
                self.log.ok(f"GC done: {collected} objects freed, RAM free={mem_free_mb()}MB")

            time.sleep(30)  # check tiap 30 detik


# ─────────────────────────────────────────────────────────
# HEARTBEAT (background thread — tulis status JSON)
# ─────────────────────────────────────────────────────────
class Heartbeat(threading.Thread):
    def __init__(self, shared, log, interval_s=60):
        super().__init__(daemon=True, name="Heartbeat")
        self.shared     = shared
        self.log        = log
        self.interval_s = interval_s

    def run(self):
        while not self.shared.get("shutdown"):
            try:
                status = {
                    "timestamp":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "elapsed_h":    round(self.shared.get("elapsed_s", 0) / 3600, 3),
                    "duty_state":   self.shared.get("duty_state", "?"),
                    "cycle_num":    self.shared.get("cycle_num", 0),
                    "fps":          round(self.shared.get("fps", 0), 2),
                    "frames":       self.shared.get("frames", 0),
                    "ram_free_mb":  self.shared.get("ram_free", 0),
                    "temp_max_c":   round(self.shared.get("temp_max", 0), 1),
                    "gc_events":    self.shared.get("gc_events", 0),
                    "thermal_events": self.shared.get("thermal_events", 0),
                    "skip_frame":   self.shared.get("skip_frame_mode", False),
                    "thermal_emergency": self.shared.get("thermal_emergency", False),
                }
                tmp = STATUS_FILE + ".tmp"
                with open(tmp, "w") as f:
                    json.dump(status, f, indent=2)
                os.replace(tmp, STATUS_FILE)  # atomic update
            except Exception as e:
                self.log.warn(f"Heartbeat error: {e}")
            time.sleep(self.interval_s)


# ─────────────────────────────────────────────────────────
# PERIODIC GC SCHEDULER
# ─────────────────────────────────────────────────────────
class PeriodicGC(threading.Thread):
    def __init__(self, cfg, shared, log):
        super().__init__(daemon=True, name="PeriodicGC")
        self.cfg    = cfg
        self.shared = shared
        self.log    = log

    def run(self):
        while not self.shared.get("shutdown"):
            time.sleep(self.cfg["gc_interval_s"])
            collected = gc.collect()
            self.shared["gc_events"] += 1
            free_mb = mem_free_mb()
            self.log.info(f"Periodic GC: {collected} objects freed | RAM={free_mb}MB free")


# ─────────────────────────────────────────────────────────
# ACTIVE PHASE — camera + YOLO + JPEG
# ─────────────────────────────────────────────────────────
def run_active_phase(detector, cam, shared, log, duration_s):
    """Jalankan full pipeline selama duration_s detik."""
    log.info(f"[ACTIVE] Start — {duration_s}s ({duration_s/60:.0f}m)")

    t_start = time.time()
    t_end   = time.time() + duration_s
    window_frames = 0
    window_start  = time.time()
    skip_count    = 0

    while time.time() < t_end and not shared.get("shutdown"):
        # Thermal emergency → bail out early
        if shared.get("thermal_emergency"):
            log.warn("[ACTIVE] Thermal emergency — aborting active phase early")
            break

        img  = cam.read()
        objs = detector.detect(img, conf_th=0.5, iou_th=0.45)

        # Annotate
        for obj in objs:
            img.draw_rect(obj.x, obj.y, obj.w, obj.h,
                          image.Color.from_rgb(255, 0, 0))

        # JPEG encode
        _ = img.to_format(image.Format.FMT_JPEG)

        # Skip-frame mode: skip every other frame to reduce NPU load
        if shared.get("skip_frame_mode"):
            skip_count += 1
            if skip_count % 2 == 0:
                time.sleep(0.01)  # brief yield to reduce heat
                continue

        shared["frames"] = shared.get("frames", 0) + 1
        window_frames   += 1

        # Compute FPS every 5 seconds
        now = time.time()
        if now - window_start >= 5.0:
            fps = window_frames / (now - window_start)
            shared["fps"] = fps
            window_frames = 0
            window_start  = now

    elapsed = time.time() - t_start
    log.info(f"[ACTIVE] Done — {elapsed:.0f}s elapsed, fps≈{shared.get('fps',0):.1f}")


# ─────────────────────────────────────────────────────────
# STANDBY PHASE — NPU idle, just monitoring
# ─────────────────────────────────────────────────────────
def run_standby_phase(shared, log, duration_s):
    """Standby: NPU off, hanya monitoring suhu dan RAM."""
    state_label = "COOLDOWN" if shared.get("thermal_emergency") else "STANDBY"
    log.info(f"[{state_label}] Start — {duration_s}s")

    t_end = time.time() + duration_s
    while time.time() < t_end and not shared.get("shutdown"):
        # Jika cooldown, tunggu sampai suhu aman ATAU durasi habis
        if shared.get("duty_state") == STATE_COOLDOWN:
            if not shared.get("thermal_emergency"):
                log.ok("[COOLDOWN] Suhu aman — keluar cooldown lebih awal")
                break
        time.sleep(2)

    log.info(f"[{state_label}] Done")


# ─────────────────────────────────────────────────────────
# CPU-ONLY ACTIVE (fallback tanpa maix)
# ─────────────────────────────────────────────────────────
def run_cpu_active_phase(shared, log, duration_s):
    log.info(f"[ACTIVE/CPU] Start — {duration_s}s")
    t_end = time.time() + duration_s
    window_frames = 0
    window_start  = time.time()
    iters = 0

    while time.time() < t_end and not shared.get("shutdown"):
        if shared.get("thermal_emergency"): break
        acc = 0.0
        for i in range(1, 3001):
            acc += math.sin(i * 0.01) * math.cos(i * 0.02)
        iters += 1
        shared["frames"] = shared.get("frames", 0) + 1
        window_frames   += 1

        now = time.time()
        if now - window_start >= 5.0:
            shared["fps"] = window_frames / (now - window_start)
            window_frames = 0
            window_start  = now

    log.info(f"[ACTIVE/CPU] Done")


# ─────────────────────────────────────────────────────────
# CHECKPOINT — log + CSV row
# ─────────────────────────────────────────────────────────
def write_checkpoint(csvlog, shared, t_start, cycle_num, log_prefix=""):
    elapsed_s = time.time() - t_start
    cum_fps   = shared.get("frames", 0) / elapsed_s if elapsed_s > 0 else 0
    temps = read_temps()
    temps_c = [c for _, _, c in temps]
    t0 = temps_c[0] if len(temps_c) > 0 else ""
    t1 = temps_c[1] if len(temps_c) > 1 else ""

    row = {
        "timestamp":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_s":     f"{elapsed_s:.0f}",
        "cycle_num":     cycle_num,
        "duty_state":    shared.get("duty_state", "?"),
        "window_fps":    f"{shared.get('fps', 0):.2f}",
        "cumulative_fps":f"{cum_fps:.2f}",
        "frames_total":  shared.get("frames", 0),
        "ram_free_mb":   shared.get("ram_free", mem_free_mb()),
        "gc_events":     shared.get("gc_events", 0),
        "temp_zone0_c":  f"{t0:.1f}" if t0 else "",
        "temp_zone1_c":  f"{t1:.1f}" if t1 else "",
        "temp_max_c":    f"{shared.get('temp_max', 0):.1f}",
        "thermal_events":shared.get("thermal_events", 0),
        "skip_frame_mode":"Y" if shared.get("skip_frame_mode") else "N",
        "watchdog_note": shared.get("watchdog_note", ""),
    }
    shared["watchdog_note"] = ""  # reset after logging
    csvlog.write(row)
    shared["elapsed_s"] = elapsed_s
    return elapsed_s, cum_fps


# ─────────────────────────────────────────────────────────
# FINAL REPORT
# ─────────────────────────────────────────────────────────
def print_final_report(shared, t_start, log):
    elapsed_s  = time.time() - t_start
    avg_fps    = shared.get("frames", 0) / elapsed_s if elapsed_s > 0 else 0

    log.ok("=" * 60)
    log.ok("LAPORAN OVERNIGHT STRESS TEST")
    log.ok("=" * 60)
    log.info(f"  Durasi actual       : {elapsed_s/3600:.2f} jam ({elapsed_s:.0f}s)")
    log.info(f"  Total frame         : {shared.get('frames',0):,}")
    log.info(f"  Rata-rata FPS       : {avg_fps:.2f}")
    log.info(f"  Siklus selesai      : {shared.get('cycle_num',0)}")
    log.info(f"  Thermal events      : {shared.get('thermal_events',0)}")
    log.info(f"  GC events           : {shared.get('gc_events',0)}")
    log.info(f"  Shutdown reason     : {shared.get('shutdown_reason','normal')}")
    log.ok("=" * 60)

    # Cleanup PID and status files
    for f in [PID_FILE, STATUS_FILE]:
        try: os.remove(f)
        except: pass


# ─────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="AuralAI Overnight Stress Test")
    parser.add_argument("--duration",    type=float, default=8,    help="Total jam (default: 8)")
    parser.add_argument("--active-min",  type=float, default=15,   help="Fase active menit (default: 15)")
    parser.add_argument("--standby-min", type=float, default=2,    help="Fase standby menit (default: 2)")
    parser.add_argument("--cooldown-min",type=float, default=5,    help="Fase cooldown menit (default: 5)")
    parser.add_argument("--temp-warn",   type=float, default=65,   help="Suhu warning °C (default: 65)")
    parser.add_argument("--temp-reduce", type=float, default=70,   help="Suhu reduce load °C (default: 70)")
    parser.add_argument("--temp-emergency",type=float,default=75,  help="Suhu emergency standby °C (default: 75)")
    parser.add_argument("--temp-safe",   type=float, default=58,   help="Suhu aman °C (default: 58)")
    parser.add_argument("--dry-run",     action="store_true",      help="CPU-only mode (tanpa kamera/NPU)")
    parser.add_argument("--model",       default=None,             help="Path ke .mud model (auto-detect)")
    args = parser.parse_args()

    # Apply overrides
    CFG["total_hours"]    = args.duration
    CFG["active_min"]     = args.active_min
    CFG["standby_min"]    = args.standby_min
    CFG["cooldown_min"]   = args.cooldown_min
    CFG["temp_warn"]      = args.temp_warn
    CFG["temp_reduce"]    = args.temp_reduce
    CFG["temp_emergency"] = args.temp_emergency
    CFG["temp_safe"]      = args.temp_safe
    CFG["model_path"]     = args.model
    dry_run = args.dry_run or not MAIX_OK

    # ── Setup output files
    os.makedirs(LOG_DIR, exist_ok=True)
    ts_str    = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path  = os.path.join(LOG_DIR, f"overnight_{ts_str}.log")
    csv_base  = os.path.join(LOG_DIR, f"overnight_{ts_str}")

    log    = DualLogger(log_path)
    csvlog = PersistentCSV(csv_base, rotate_mb=CFG["csv_rotate_mb"])

    # ── Write PID
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    # ── Shared state (thread-safe via GIL for simple types)
    shared = {
        "shutdown":         False,
        "shutdown_reason":  "normal",
        "duty_state":       STATE_ACTIVE,
        "cycle_num":        0,
        "fps":              0.0,
        "frames":           0,
        "ram_free":         mem_free_mb(),
        "temp_max":         0.0,
        "gc_events":        0,
        "thermal_events":   0,
        "thermal_emergency":False,
        "skip_frame_mode":  False,
        "elapsed_s":        0,
        "watchdog_note":    "",
    }

    # ── Signal handlers
    def graceful_shutdown(signum, frame):
        log.warn(f"Signal {signum} received — graceful shutdown...")
        shared["shutdown"] = True
        shared["shutdown_reason"] = f"signal_{signum}"

    signal.signal(signal.SIGTERM, graceful_shutdown)
    signal.signal(signal.SIGINT,  graceful_shutdown)

    # ── Print config
    log.ok("=" * 60)
    log.ok("AuralAI Overnight Stress Test v1")
    log.ok("=" * 60)
    log.info(f"  Mode          : {'DRY RUN (CPU only)' if dry_run else 'LIVE (MaixCAM)'}")
    log.info(f"  Duration      : {CFG['total_hours']}h  ({CFG['total_hours']*3600:.0f}s)")
    log.info(f"  Duty cycle    : {CFG['active_min']}m active + {CFG['standby_min']}m standby")
    log.info(f"  Thermal       : warn={CFG['temp_warn']}°C  reduce={CFG['temp_reduce']}°C  emergency={CFG['temp_emergency']}°C")
    log.info(f"  Memory GC     : tiap {CFG['gc_interval_s']//60}m, critical={CFG['ram_critical']}MB")
    log.info(f"  Log           : {log_path}")
    log.info(f"  CSV           : {csv_base}_partN.csv")
    log.info(f"  PID           : {PID_FILE}")
    log.info(f"  Status JSON   : {STATUS_FILE}")
    log.info(f"  Stop cleanly  : kill -TERM {os.getpid()}")
    log.ok("=" * 60)

    # ── Load model & camera (live mode)
    detector = None
    cam      = None
    if not dry_run:
        model_path = find_yolo_model(CFG["model_path"])
        if not model_path:
            log.warn("YOLO model tidak ditemukan → DRY RUN fallback")
            dry_run = True
        else:
            log.info(f"Loading model: {model_path}")
            try:
                if   "yolo11" in model_path: detector = nn.YOLO11(model=model_path, dual_buff=True)
                elif "yolov8" in model_path: detector = nn.YOLOv8(model=model_path, dual_buff=True)
                else:                        detector = nn.YOLOv5(model=model_path, dual_buff=True)

                cam = camera.Camera(
                    detector.input_width(), detector.input_height(), detector.input_format()
                )
                log.ok(f"Camera + model OK ({detector.input_width()}×{detector.input_height()})")
                for _ in range(10):  # warmup
                    img = cam.read()
                    _ = detector.detect(img)
                log.ok("Warmup selesai")
            except Exception as ex:
                log.error(f"Init error: {ex} → DRY RUN fallback")
                dry_run = True
                detector = None; cam = None

    # ── Start watchdog threads
    ThermalWatchdog(CFG, shared, log).start()
    MemoryGuardian(CFG, shared, log).start()
    PeriodicGC(CFG, shared, log).start()
    Heartbeat(shared, log, CFG["heartbeat_s"]).start()

    log.ok("Semua watchdog aktif. Memulai duty cycle loop...")

    # ── Main duty cycle loop
    t_start      = time.time()
    total_s      = CFG["total_hours"] * 3600
    active_s     = CFG["active_min"]  * 60
    standby_s    = CFG["standby_min"] * 60
    cooldown_s   = CFG["cooldown_min"]* 60
    cycle_num    = 0

    try:
        while not shared.get("shutdown"):
            elapsed = time.time() - t_start
            if elapsed >= total_s:
                log.ok("Durasi target tercapai — shutdown normal")
                shared["shutdown_reason"] = "duration_complete"
                break

            remaining = total_s - elapsed
            cycle_num += 1
            shared["cycle_num"] = cycle_num

            # ── ACTIVE PHASE ──────────────────────────────
            if not shared.get("thermal_emergency"):
                shared["duty_state"] = STATE_ACTIVE
                phase_dur = min(active_s, remaining)
                log.info(f"--- CYCLE {cycle_num} | elapsed={elapsed/3600:.2f}h | "
                         f"duty=ACTIVE | fps={shared.get('fps',0):.1f} | "
                         f"temp={shared.get('temp_max',0):.1f}°C | "
                         f"RAM={shared.get('ram_free',0)}MB ---")

                if dry_run:
                    run_cpu_active_phase(shared, log, phase_dur)
                else:
                    run_active_phase(detector, cam, shared, log, phase_dur)

                write_checkpoint(csvlog, shared, t_start, cycle_num)
            else:
                log.warn(f"--- CYCLE {cycle_num} | THERMAL EMERGENCY — skip active phase ---")

            if shared.get("shutdown"): break

            # ── STANDBY / COOLDOWN PHASE ──────────────────
            if shared.get("thermal_emergency"):
                shared["duty_state"] = STATE_COOLDOWN
                phase_dur = cooldown_s
                log.warn(f"[COOLDOWN] suhu={shared.get('temp_max',0):.1f}°C > {CFG['temp_emergency']}°C")
            else:
                shared["duty_state"] = STATE_STANDBY
                phase_dur = min(standby_s, remaining)

            remaining = total_s - (time.time() - t_start)
            if remaining <= 0: break
            phase_dur = min(phase_dur, remaining)

            run_standby_phase(shared, log, phase_dur)
            write_checkpoint(csvlog, shared, t_start, cycle_num)

    except Exception as ex:
        log.error(f"Main loop exception: {ex}")
        shared["shutdown_reason"] = f"exception: {ex}"

    finally:
        shared["shutdown"] = True  # stop all daemon threads

        log.info("Membersihkan resources...")
        if cam:
            try: del cam
            except: pass
        if detector:
            try: del detector
            except: pass
        gc.collect()

        print_final_report(shared, t_start, log)
        csvlog.close()
        log.close()


if __name__ == "__main__":
    main()

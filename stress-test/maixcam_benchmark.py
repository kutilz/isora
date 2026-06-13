"""
MaixCAM Benchmark & Thermal Stress Test
========================================
Target  : MaixCAM (regular) – SG2002 / RISC-V C906 + ARM A53
Runtime : MaixPy (MaixVision)
Author  : Albert (AuralAI / IIoT Lab – UPI)

Sections
--------
0. System Info
1. Thermal Baseline
2. Camera Capture Benchmark
3. Image Processing Benchmark
4. CPU Math Stress Test
5. YOLO Inference Benchmark (requires /root/models/yolov5s.mud)
6. Sustained Thermal Stress (CPU + Camera + ImgOps combined)
7. Final Report
"""

import os
import sys
import time
import math

# ──────────────────────────────────────────────
# Try importing maix modules gracefully
# ──────────────────────────────────────────────
try:
    from maix import camera, image, display, nn, app
    MAIX_OK = True
except ImportError as e:
    print(f"[WARN] maix import failed: {e}")
    MAIX_OK = False

# ═══════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════

DIVIDER  = "=" * 60
DIVIDER2 = "-" * 60

def ts_ms():
    """Millisecond timestamp."""
    return time.time() * 1000.0

def print_section(title):
    print()
    print(DIVIDER)
    print(f"  {title}")
    print(DIVIDER)

def print_sub(label, value=""):
    if value:
        print(f"  {label:<35} {value}")
    else:
        print(f"  {label}")

# ──────────────────────────────────────────────
# Thermal reading
# ──────────────────────────────────────────────
THERMAL_ZONES = []

def _discover_thermal_zones():
    global THERMAL_ZONES
    THERMAL_ZONES = []
    base = "/sys/class/thermal"
    if not os.path.exists(base):
        return
    for entry in sorted(os.listdir(base)):
        if not entry.startswith("thermal_zone"):
            continue
        zone_path = os.path.join(base, entry)
        temp_path = os.path.join(zone_path, "temp")
        type_path = os.path.join(zone_path, "type")
        if not os.path.exists(temp_path):
            continue
        zone_type = "unknown"
        try:
            with open(type_path) as f:
                zone_type = f.read().strip()
        except Exception:
            pass
        THERMAL_ZONES.append((entry, zone_type, temp_path))

def read_all_temps():
    """Returns list of (zone_name, zone_type, temp_C)."""
    results = []
    for zone_name, zone_type, temp_path in THERMAL_ZONES:
        try:
            with open(temp_path) as f:
                raw = int(f.read().strip())
            # SG2002 reports in millidegrees
            temp_c = raw / 1000.0 if raw > 1000 else float(raw)
            results.append((zone_name, zone_type, temp_c))
        except Exception:
            results.append((zone_name, zone_type, None))
    return results

def print_temps(label=""):
    temps = read_all_temps()
    if not temps:
        print_sub(f"{label}Temperature", "N/A (no thermal zones found)")
        return
    for zone_name, zone_type, temp_c in temps:
        val = f"{temp_c:.1f} °C" if temp_c is not None else "read error"
        print_sub(f"{label}[{zone_name}] {zone_type}", val)

# ──────────────────────────────────────────────
# /proc parsers
# ──────────────────────────────────────────────
def read_proc(path):
    try:
        with open(path) as f:
            return f.read()
    except Exception:
        return ""

def parse_meminfo():
    data = read_proc("/proc/meminfo")
    mem = {}
    for line in data.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            key = parts[0].rstrip(":")
            val = int(parts[1])
            mem[key] = val
    return mem

def parse_cpuinfo():
    data = read_proc("/proc/cpuinfo")
    cores = []
    current = {}
    for line in data.splitlines():
        if line.strip() == "":
            if current:
                cores.append(current)
                current = {}
        elif ":" in line:
            k, _, v = line.partition(":")
            current[k.strip()] = v.strip()
    if current:
        cores.append(current)
    return cores

def read_loadavg():
    data = read_proc("/proc/loadavg")
    return data.strip()

def read_uptime():
    data = read_proc("/proc/uptime")
    parts = data.split()
    if parts:
        secs = float(parts[0])
        h, rem = divmod(int(secs), 3600)
        m, s = divmod(rem, 60)
        return f"{h}h {m}m {s}s"
    return "N/A"

def read_cpu_freq():
    """Read current CPU freq for each possible CPU."""
    freqs = []
    for i in range(8):
        path = f"/sys/devices/system/cpu/cpu{i}/cpufreq/scaling_cur_freq"
        if os.path.exists(path):
            try:
                with open(path) as f:
                    khz = int(f.read().strip())
                freqs.append((i, khz // 1000))  # MHz
            except Exception:
                pass
    return freqs

def read_cpu_max_freq():
    freqs = []
    for i in range(8):
        path = f"/sys/devices/system/cpu/cpu{i}/cpufreq/cpuinfo_max_freq"
        if os.path.exists(path):
            try:
                with open(path) as f:
                    khz = int(f.read().strip())
                freqs.append((i, khz // 1000))
            except Exception:
                pass
    return freqs

def read_npu_freq():
    candidates = [
        "/sys/class/clk/clk_tpu/clk_rate",
        "/sys/kernel/debug/clk/clk_tpu/clk_rate",
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                with open(p) as f:
                    return int(f.read().strip()) // 1_000_000
            except Exception:
                pass
    return None


# ═══════════════════════════════════════════════════════════════════
# SECTION 0 – SYSTEM INFO
# ═══════════════════════════════════════════════════════════════════
def section_system_info():
    print_section("SECTION 0 – SYSTEM INFO")

    # OS / kernel
    uname = os.uname()
    print_sub("OS / Sysname",  uname.sysname)
    print_sub("Hostname",       uname.nodename)
    print_sub("Kernel Release", uname.release)
    print_sub("Kernel Version", uname.version)
    print_sub("Architecture",   uname.machine)
    print_sub("Uptime",         read_uptime())
    print_sub("Load Average",   read_loadavg())

    print()

    # CPU info
    cores = parse_cpuinfo()
    print_sub(f"CPU Cores Detected: {len(cores)}")
    for i, core in enumerate(cores):
        model  = core.get("model name", core.get("uarch", core.get("isa", "N/A")))
        hw     = core.get("Hardware", "")
        print_sub(f"  Core {i}", f"{model} {hw}".strip())

    cur_freqs = read_cpu_freq()
    max_freqs = read_cpu_max_freq()
    if cur_freqs:
        for cpu_id, mhz in cur_freqs:
            print_sub(f"  CPU{cpu_id} Current Freq", f"{mhz} MHz")
    if max_freqs:
        for cpu_id, mhz in max_freqs:
            print_sub(f"  CPU{cpu_id} Max Freq",     f"{mhz} MHz")

    npu_mhz = read_npu_freq()
    if npu_mhz:
        print_sub("NPU Freq", f"{npu_mhz} MHz")

    print()

    # Memory
    mem = parse_meminfo()
    total_mb = mem.get("MemTotal",     0) // 1024
    free_mb  = mem.get("MemFree",      0) // 1024
    avail_mb = mem.get("MemAvailable", 0) // 1024
    buff_mb  = mem.get("Buffers",      0) // 1024
    cache_mb = mem.get("Cached",       0) // 1024
    used_mb  = total_mb - free_mb
    print_sub("RAM Total",     f"{total_mb} MB")
    print_sub("RAM Used",      f"{used_mb} MB")
    print_sub("RAM Free",      f"{free_mb} MB")
    print_sub("RAM Available", f"{avail_mb} MB")
    print_sub("Buffers+Cache", f"{buff_mb + cache_mb} MB")

    print()

    # Disk
    try:
        stat = os.statvfs("/root")
        total_gb = (stat.f_blocks * stat.f_frsize) / (1024**3)
        free_gb  = (stat.f_bavail * stat.f_frsize) / (1024**3)
        used_gb  = total_gb - free_gb
        print_sub("Disk /root Total", f"{total_gb:.2f} GB")
        print_sub("Disk /root Used",  f"{used_gb:.2f} GB")
        print_sub("Disk /root Free",  f"{free_gb:.2f} GB")
    except Exception as e:
        print_sub("Disk /root", f"Error: {e}")

    print()

    # Python
    print_sub("Python Version", sys.version.replace("\n", " "))
    print_sub("MaixPy Available", "YES" if MAIX_OK else "NO")


# ═══════════════════════════════════════════════════════════════════
# SECTION 1 – THERMAL BASELINE
# ═══════════════════════════════════════════════════════════════════
def section_thermal_baseline():
    print_section("SECTION 1 – THERMAL BASELINE (idle)")
    _discover_thermal_zones()

    if not THERMAL_ZONES:
        print_sub("No thermal zones found in /sys/class/thermal")
        print_sub("Possible reason: kernel config or non-standard BSP")
        return

    print_sub(f"Found {len(THERMAL_ZONES)} thermal zone(s)")
    print()
    print_temps("Baseline  ")


# ═══════════════════════════════════════════════════════════════════
# SECTION 2 – CAMERA CAPTURE BENCHMARK
# ═══════════════════════════════════════════════════════════════════
def section_camera_benchmark():
    print_section("SECTION 2 – CAMERA CAPTURE BENCHMARK")

    if not MAIX_OK:
        print_sub("SKIPPED – maix not available")
        return

    configs = [
        (320, 240,  "QVGA   320x240"),
        (640, 480,  "VGA    640x480"),
        (1280, 720, "HD    1280x720"),
    ]

    results = {}

    for w, h, label in configs:
        print()
        print_sub(f"Testing {label} ...")
        try:
            cam = camera.Camera(w, h)
            # Warm-up
            for _ in range(10):
                img = cam.read()

            # Benchmark
            FRAMES = 100
            t_start = ts_ms()
            for _ in range(FRAMES):
                img = cam.read()
            t_end = ts_ms()
            elapsed_ms = t_end - t_start
            fps = FRAMES / (elapsed_ms / 1000.0)
            per_frame = elapsed_ms / FRAMES

            print_sub(f"  Frames captured",       f"{FRAMES}")
            print_sub(f"  Total time",             f"{elapsed_ms:.1f} ms")
            print_sub(f"  Average per frame",      f"{per_frame:.2f} ms")
            print_sub(f"  Measured FPS",           f"{fps:.1f} fps")

            results[label] = fps

            # Cleanup
            del cam

        except Exception as e:
            print_sub(f"  ERROR", str(e))
            results[label] = None

    print()
    print_sub("Camera Benchmark Summary:")
    for label, fps in results.items():
        val = f"{fps:.1f} fps" if fps else "FAILED"
        print_sub(f"  {label}", val)

    return results


# ═══════════════════════════════════════════════════════════════════
# SECTION 3 – IMAGE PROCESSING BENCHMARK
# ═══════════════════════════════════════════════════════════════════
def section_image_benchmark():
    print_section("SECTION 3 – IMAGE PROCESSING BENCHMARK")

    if not MAIX_OK:
        print_sub("SKIPPED – maix not available")
        return

    ITERS = 200
    results = {}

    # ── 3a. draw_rect
    def bench_draw_rect():
        img = image.Image(320, 240, image.Format.FMT_RGB888)
        t = ts_ms()
        for _ in range(ITERS):
            img.draw_rect(10, 10, 200, 150, image.Color.from_rgb(255, 0, 0))
        return ts_ms() - t

    # ── 3b. draw_string
    def bench_draw_string():
        img = image.Image(320, 240, image.Format.FMT_RGB888)
        t = ts_ms()
        for _ in range(ITERS):
            img.draw_string(10, 10, "Hello MaixPy Benchmark!", image.Color.from_rgb(255, 255, 0))
        return ts_ms() - t

    # ── 3c. resize (320x240 → 160x120)
    def bench_resize():
        img = image.Image(320, 240, image.Format.FMT_RGB888)
        t = ts_ms()
        for _ in range(ITERS):
            img.resize(160, 120)
        return ts_ms() - t

    # ── 3d. crop
    def bench_crop():
        img = image.Image(320, 240, image.Format.FMT_RGB888)
        t = ts_ms()
        for _ in range(ITERS):
            img.crop(0, 0, 160, 120)
        return ts_ms() - t

    # ── 3e. to_format RGB→BGR
    def bench_to_format():
        img = image.Image(320, 240, image.Format.FMT_RGB888)
        t = ts_ms()
        for _ in range(ITERS):
            img.to_format(image.Format.FMT_BGR888)
        return ts_ms() - t

    # ── 3f. to_format RGB→JPEG
    def bench_to_jpeg():
        img = image.Image(320, 240, image.Format.FMT_RGB888)
        t = ts_ms()
        for _ in range(ITERS):
            img.to_format(image.Format.FMT_JPEG)
        return ts_ms() - t

    # ── 3g. copy
    def bench_copy():
        img = image.Image(320, 240, image.Format.FMT_RGB888)
        t = ts_ms()
        for _ in range(ITERS):
            img.copy()
        return ts_ms() - t

    # ── 3h. draw_circle x50 per iter
    def bench_draw_circle():
        img = image.Image(320, 240, image.Format.FMT_RGB888)
        t = ts_ms()
        for _ in range(ITERS):
            for r in range(5, 55, 10):
                img.draw_circle(160, 120, r, image.Color.from_rgb(0, 255, 0))
        return ts_ms() - t

    # ── 3i. rotate
    def bench_rotate():
        img = image.Image(320, 240, image.Format.FMT_RGB888)
        t = ts_ms()
        for _ in range(ITERS):
            img.rotate(90)
        return ts_ms() - t

    # ── 3j. draw_line x20 per iter
    def bench_draw_lines():
        img = image.Image(320, 240, image.Format.FMT_RGB888)
        t = ts_ms()
        for _ in range(ITERS):
            for k in range(20):
                img.draw_line(0, k*12, 320, 240-k*12, image.Color.from_rgb(255, 128, 0))
        return ts_ms() - t

    # ── 3k. to_bytes (memory bandwidth)
    def bench_to_bytes():
        img = image.Image(640, 480, image.Format.FMT_RGB888)
        t = ts_ms()
        for _ in range(ITERS):
            _ = img.to_bytes()
        return ts_ms() - t

    benchmarks = [
        ("draw_rect       (320x240, 200 iters)", bench_draw_rect),
        ("draw_string     (320x240, 200 iters)", bench_draw_string),
        ("resize 320→160  (320x240, 200 iters)", bench_resize),
        ("crop 320→160    (320x240, 200 iters)", bench_crop),
        ("to_format RGB→BGR (320x240,200 iters)", bench_to_format),
        ("to_format RGB→JPEG(320x240,200 iters)", bench_to_jpeg),
        ("copy            (320x240, 200 iters)", bench_copy),
        ("draw_circle x5  (320x240, 200 iters)", bench_draw_circle),
        ("rotate 90°      (320x240, 200 iters)", bench_rotate),
        ("draw_line x20   (320x240, 200 iters)", bench_draw_lines),
        ("to_bytes        (640x480, 200 iters)", bench_to_bytes),
    ]

    print()
    for name, fn in benchmarks:
        try:
            elapsed = fn()
            per_op  = elapsed / ITERS
            ops_sec = 1000.0 / per_op
            print_sub(name)
            print_sub(f"    Total: {elapsed:.1f} ms  |  Per-op: {per_op:.3f} ms  |  Throughput: {ops_sec:.1f} ops/s")
            results[name] = (elapsed, per_op, ops_sec)
        except Exception as e:
            print_sub(name, f"ERROR: {e}")

    return results


# ═══════════════════════════════════════════════════════════════════
# SECTION 4 – CPU MATH STRESS TEST
# ═══════════════════════════════════════════════════════════════════
def section_cpu_stress():
    print_section("SECTION 4 – CPU MATH STRESS TEST")

    results = {}

    # ── 4a. Integer arithmetic
    def bench_int_arith(n=5_000_000):
        t = ts_ms()
        acc = 0
        for i in range(n):
            acc += i * 3 - i // 2 + (i % 7)
        elapsed = ts_ms() - t
        return elapsed, n / (elapsed / 1000.0)

    # ── 4b. Float arithmetic
    def bench_float_arith(n=2_000_000):
        t = ts_ms()
        acc = 0.0
        for i in range(1, n + 1):
            acc += math.sqrt(float(i)) * 1.41421 / float(i)
        elapsed = ts_ms() - t
        return elapsed, n / (elapsed / 1000.0)

    # ── 4c. Trig (sin/cos)
    def bench_trig(n=500_000):
        t = ts_ms()
        acc = 0.0
        step = 2 * math.pi / n
        for i in range(n):
            acc += math.sin(i * step) + math.cos(i * step)
        elapsed = ts_ms() - t
        return elapsed, n / (elapsed / 1000.0)

    # ── 4d. String ops
    def bench_string(n=100_000):
        t = ts_ms()
        base = "MaixCAM_Benchmark_Test_"
        s = ""
        for i in range(n):
            s = base + str(i % 9999)
            _ = len(s)
        elapsed = ts_ms() - t
        return elapsed, n / (elapsed / 1000.0)

    # ── 4e. List operations
    def bench_list(n=1_000_000):
        t = ts_ms()
        lst = list(range(1000))
        for _ in range(n // 1000):
            lst.sort()
            lst.reverse()
        elapsed = ts_ms() - t
        return elapsed, (n // 1000) / (elapsed / 1000.0)

    # ── 4f. Recursive Fibonacci (single call to deep fib)
    def fib(n):
        if n <= 1:
            return n
        return fib(n-1) + fib(n-2)

    def bench_fib(depth=30):
        t = ts_ms()
        result = fib(depth)
        elapsed = ts_ms() - t
        return elapsed, result

    # ── 4g. SHA256 hash throughput
    def bench_hash(n=5000):
        import hashlib
        data = b"MaixCAM thermal benchmark payload" * 64  # 2KB block
        t = ts_ms()
        for _ in range(n):
            hashlib.sha256(data).hexdigest()
        elapsed = ts_ms() - t
        mb_sec = (n * len(data)) / (elapsed / 1000.0) / 1024 / 1024
        return elapsed, mb_sec

    # ── 4h. Memory allocation stress
    def bench_memalloc(n=5000):
        t = ts_ms()
        for _ in range(n):
            buf = bytearray(4096)
            buf[0] = 0xFF
            del buf
        elapsed = ts_ms() - t
        return elapsed, n / (elapsed / 1000.0)

    print()
    print_sub("Running integer arithmetic (5M ops)...")
    elapsed, ops = bench_int_arith()
    print_sub("  Integer arith", f"{elapsed:.1f} ms  |  {ops/1e6:.2f} Mops/s")
    results["int_arith"] = ops

    print()
    print_sub("Running float + sqrt (2M ops)...")
    elapsed, ops = bench_float_arith()
    print_sub("  Float+sqrt",    f"{elapsed:.1f} ms  |  {ops/1e6:.2f} Mops/s")
    results["float_arith"] = ops

    print()
    print_sub("Running sin/cos trig (500K ops)...")
    elapsed, ops = bench_trig()
    print_sub("  Trig sin+cos",  f"{elapsed:.1f} ms  |  {ops/1e3:.2f} Kops/s")
    results["trig"] = ops

    print()
    print_sub("Running string ops (100K ops)...")
    elapsed, ops = bench_string()
    print_sub("  String ops",    f"{elapsed:.1f} ms  |  {ops/1e3:.2f} Kops/s")
    results["string"] = ops

    print()
    print_sub("Running list sort/reverse (1K-element list, 1K rounds)...")
    elapsed, ops = bench_list()
    print_sub("  List sort+rev", f"{elapsed:.1f} ms  |  {ops:.1f} rounds/s")
    results["list"] = ops

    print()
    print_sub("Running recursive Fibonacci(30)...")
    elapsed, result = bench_fib(30)
    print_sub("  Fib(30)", f"{result}  computed in {elapsed:.1f} ms")
    results["fib"] = elapsed

    print()
    print_sub("Running SHA-256 hash (5000 x 2KB blocks)...")
    try:
        elapsed, mb_sec = bench_hash()
        print_sub("  SHA-256",        f"{elapsed:.1f} ms  |  {mb_sec:.2f} MB/s")
        results["sha256"] = mb_sec
    except Exception as e:
        print_sub("  SHA-256",        f"Error: {e}")

    print()
    print_sub("Running memory alloc/free (5000 x 4KB blocks)...")
    elapsed, ops = bench_memalloc()
    print_sub("  Mem alloc/free", f"{elapsed:.1f} ms  |  {ops:.1f} alloc/s")
    results["memalloc"] = ops

    print()
    print_temps("Post-CPU-stress  ")

    return results


# ═══════════════════════════════════════════════════════════════════
# SECTION 5 – YOLO INFERENCE BENCHMARK
# ═══════════════════════════════════════════════════════════════════
def section_yolo_benchmark():
    print_section("SECTION 5 – YOLO INFERENCE BENCHMARK (NPU/AI)")

    if not MAIX_OK:
        print_sub("SKIPPED – maix not available")
        return

    model_candidates = [
        ("/root/models/yolo11n.mud", "YOLO11n"),
        ("/root/models/yolov8n.mud", "YOLOv8n"),
        ("/root/models/yolov5s.mud", "YOLOv5s"),
    ]

    found_model = None
    found_label = None
    for path, label in model_candidates:
        if os.path.exists(path):
            found_model = path
            found_label = label
            break

    if not found_model:
        print_sub("Model file NOT found. Checked:")
        for path, label in model_candidates:
            print_sub(f"  {path}", "missing")
        print_sub("Upload a YOLO .mud model to /root/models/ to enable this section.")
        print_sub("Download: https://maixhub.com/model/zoo/453  (YOLO11)")
        return

    print_sub("Using model", f"{found_label}  ({found_model})")
    print()

    try:
        if "yolo11" in found_model.lower() or "yolo11" in found_label.lower():
            detector = nn.YOLO11(model=found_model, dual_buff=True)
        elif "yolov8" in found_model.lower() or "yolov8" in found_label.lower():
            detector = nn.YOLOv8(model=found_model, dual_buff=True)
        else:
            detector = nn.YOLOv5(model=found_model, dual_buff=True)

        in_w = detector.input_width()
        in_h = detector.input_height()
        print_sub("Model input size", f"{in_w}x{in_h}")

        cam = camera.Camera(in_w, in_h, detector.input_format())

        # Warm-up
        print_sub("Warming up (20 frames)...")
        for _ in range(20):
            img = cam.read()
            _ = detector.detect(img, conf_th=0.5, iou_th=0.45)

        print_sub("Benchmarking inference (100 frames)...")
        FRAMES = 100
        t_start = ts_ms()
        for _ in range(FRAMES):
            img = cam.read()
            objs = detector.detect(img, conf_th=0.5, iou_th=0.45)
        t_end   = ts_ms()
        elapsed  = t_end - t_start
        fps      = FRAMES / (elapsed / 1000.0)
        per_inf  = elapsed / FRAMES

        print()
        print_sub("Frames run",            f"{FRAMES}")
        print_sub("Total time",            f"{elapsed:.1f} ms")
        print_sub("Average inference time",f"{per_inf:.2f} ms / frame")
        print_sub("End-to-end FPS",        f"{fps:.1f} fps")
        print_sub("Objects in last frame", f"{len(objs)}")
        if objs:
            for o in objs[:5]:  # show up to 5 detections
                lbl = detector.labels[o.class_id] if hasattr(detector, 'labels') else str(o.class_id)
                print_sub(f"  detected", f"{lbl}  score={o.score:.2f}  @ ({o.x},{o.y},{o.w}x{o.h})")

        print()
        print_temps("Post-YOLO  ")

        del cam
        del detector

    except Exception as e:
        print_sub("ERROR during YOLO benchmark", str(e))
        import traceback
        traceback.print_exc()


# ═══════════════════════════════════════════════════════════════════
# SECTION 6 – SUSTAINED THERMAL STRESS TEST
# ═══════════════════════════════════════════════════════════════════
def section_thermal_stress():
    print_section("SECTION 6 – SUSTAINED THERMAL STRESS TEST")
    print_sub("Duration: 60 seconds of combined CPU + Camera + ImgOps load")
    print_sub("Thermal readings logged every 10 seconds")
    print()

    DURATION_S = 60
    LOG_INTERVAL_S = 10

    if not MAIX_OK:
        # CPU-only stress
        print_sub("maix not available – running CPU-only stress")
        t_end   = time.time() + DURATION_S
        t_log   = time.time() + LOG_INTERVAL_S
        elapsed = 0
        iters   = 0
        while time.time() < t_end:
            # Burn CPU
            acc = 0.0
            for i in range(1, 5001):
                acc += math.sin(i) * math.cos(i) / math.sqrt(i)
            iters += 1
            if time.time() >= t_log:
                elapsed = DURATION_S - (t_end - time.time())
                print_sub(f"  t={elapsed:.0f}s  iters={iters}")
                print_temps("    ")
                t_log += LOG_INTERVAL_S
        print_sub(f"Stress complete  total_iters={iters}")
        return

    # Full stress: Camera + ImgOps + CPU math
    try:
        cam = camera.Camera(320, 240)
    except Exception as e:
        print_sub("Camera init failed", str(e))
        cam = None

    max_temp    = {}
    frame_count = 0
    t_start_abs = time.time()
    t_end_abs   = time.time() + DURATION_S
    t_log_abs   = time.time() + LOG_INTERVAL_S

    print_sub("Starting stress loop...")
    print()

    while time.time() < t_end_abs:
        # ── Camera read
        if cam:
            try:
                img = cam.read()
            except Exception:
                img = image.Image(320, 240, image.Format.FMT_RGB888)
        else:
            img = image.Image(320, 240, image.Format.FMT_RGB888)

        # ── Image operations (deliberately heavy)
        img.draw_rect(0, 0, 320, 240, image.Color.from_rgb(255, 0, 0), thickness=2)
        img.draw_string(10, 10, "STRESS TEST RUNNING", image.Color.from_rgb(255, 255, 0))
        for k in range(10):
            img.draw_line(0, k*24, 320, 240-k*24, image.Color.from_rgb(0, 128, 255))
        for r in [20, 40, 60, 80]:
            img.draw_circle(160, 120, r, image.Color.from_rgb(0, 255, 0))
        _ = img.resize(160, 120)
        _ = img.to_format(image.Format.FMT_JPEG)

        # ── CPU math burn
        acc = 0.0
        for i in range(1, 1001):
            acc += math.sin(i * 0.01) * math.cos(i * 0.01)

        frame_count += 1

        # ── Periodic thermal log
        if time.time() >= t_log_abs:
            elapsed = time.time() - t_start_abs
            fps_now = frame_count / elapsed if elapsed > 0 else 0
            mem     = parse_meminfo()
            free_mb = mem.get("MemFree", 0) // 1024

            print_sub(f"  t={elapsed:.0f}s  frames={frame_count}  fps={fps_now:.1f}  mem_free={free_mb}MB")
            temps = read_all_temps()
            for zone_name, zone_type, temp_c in temps:
                if temp_c is not None:
                    val_str = f"{temp_c:.1f} °C"
                    print_sub(f"    [{zone_name}] {zone_type}", val_str)
                    # Track max
                    if zone_name not in max_temp or temp_c > max_temp[zone_name]:
                        max_temp[zone_name] = temp_c
            print()
            t_log_abs += LOG_INTERVAL_S

    elapsed_total = time.time() - t_start_abs
    final_fps     = frame_count / elapsed_total

    print()
    print(DIVIDER2)
    print_sub("Stress Test Complete!")
    print_sub("Total frames processed", str(frame_count))
    print_sub("Total time",             f"{elapsed_total:.1f} s")
    print_sub("Average FPS (full loop)",f"{final_fps:.1f} fps")
    print()
    print_sub("Peak temperatures during stress:")
    if max_temp:
        for zone, t in max_temp.items():
            print_sub(f"  {zone}", f"{t:.1f} °C  (PEAK)")
    else:
        print_sub("  No thermal data recorded")

    if cam:
        del cam


# ═══════════════════════════════════════════════════════════════════
# SECTION 7 – FINAL REPORT
# ═══════════════════════════════════════════════════════════════════
def section_final_report(cam_results, img_results, cpu_results):
    print_section("SECTION 7 – FINAL REPORT")

    print()
    print_sub("── CAMERA CAPTURE THROUGHPUT ──")
    if cam_results:
        for label, fps in cam_results.items():
            v = f"{fps:.1f} fps" if fps else "FAILED"
            print_sub(f"  {label}", v)
    else:
        print_sub("  No results (maix unavailable or skipped)")

    print()
    print_sub("── CPU PERFORMANCE ──")
    if cpu_results:
        if "int_arith"  in cpu_results: print_sub("  Integer arith",    f"{cpu_results['int_arith']/1e6:.2f} Mops/s")
        if "float_arith"in cpu_results: print_sub("  Float+sqrt",       f"{cpu_results['float_arith']/1e6:.2f} Mops/s")
        if "trig"       in cpu_results: print_sub("  Trig (sin+cos)",   f"{cpu_results['trig']/1e3:.2f} Kops/s")
        if "sha256"     in cpu_results: print_sub("  SHA-256",          f"{cpu_results['sha256']:.2f} MB/s")
        if "memalloc"   in cpu_results: print_sub("  Mem alloc/free",   f"{cpu_results['memalloc']:.1f} ops/s")
        if "fib"        in cpu_results: print_sub("  Fib(30) latency",  f"{cpu_results['fib']:.1f} ms")
    else:
        print_sub("  No results")

    print()
    print_sub("── THERMAL SUMMARY ──")
    print_temps("  Final idle  ")

    print()
    print(DIVIDER)
    print("  Benchmark complete. Check peaks in Section 6 for thermal limits.")
    print(DIVIDER)


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════
def main():
    print()
    print(DIVIDER)
    print("  MaixCAM Comprehensive Benchmark & Thermal Stress Test")
    print(f"  Started: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(DIVIDER)

    _discover_thermal_zones()

    section_system_info()
    section_thermal_baseline()
    cam_results = section_camera_benchmark()
    img_results = section_image_benchmark()
    cpu_results = section_cpu_stress()
    section_yolo_benchmark()
    section_thermal_stress()
    section_final_report(cam_results, img_results, cpu_results)

    print(f"\n  Finished: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print()


if __name__ == "__main__":
    main()

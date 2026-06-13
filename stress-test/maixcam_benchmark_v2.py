"""
MaixCAM Proper Stress & Capability Benchmark v2
=================================================
Target  : MaixCAM (regular) – SG2002 / RISC-V C906 + NPU 1TOPS
Runtime : MaixPy (MaixVision)

Filosofi benchmark ini:
- Camera fps bukan benchmark – itu hardware cap (GC4653 = 60fps, titik)
- CPU float math bukan benchmark – RISC-V C906 memang lambat, pakai NPU
- Yang diukur: NPU throughput, memory bandwidth, pipeline end-to-end,
  dan concurrent load (relevan ke arsitektur 2-thread AuralAI)

Sections:
  0. System Info + Thermal Baseline
  1. Memory Bandwidth (bottleneck nyata embedded system)
  2. JPEG Codec Throughput (I/O & CPU codec pipeline)
  3. NPU Inference Benchmark – sustained YOLO (NPU-only)
  4. Full Pipeline Benchmark – Camera → NPU → JPEG encode (end-to-end fps)
  5. Concurrent Stress – simulasi 2-thread: AI loop + web server (AuralAI pattern)
  6. Thermal Endurance – 90s sustained full pipeline, log suhu tiap 15s
  7. Final Report
"""

import os, sys, time, math, threading, gc

try:
    from maix import camera, image, nn, app
    MAIX_OK = True
except ImportError as e:
    print(f"[WARN] maix import: {e}")
    MAIX_OK = False

# ─────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────
DIV  = "=" * 62
DIV2 = "-" * 62

def ts()   : return time.time()
def ts_ms(): return time.time() * 1000.0

def pr(label, val=""):
    if val: print(f"  {label:<38} {val}")
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
        t_raw = read_file(f"{base}/{entry}/temp")
        t_type= read_file(f"{base}/{entry}/type") or "unknown"
        if t_raw:
            try:
                val = int(t_raw)
                c   = val / 1000.0 if val > 1000 else float(val)
                zones.append((entry, t_type, c))
            except: pass
    return zones

def log_temps(prefix=""):
    zones = read_temps()
    if not zones:
        pr(f"{prefix}Temperature", "N/A – no sysfs thermal zone")
        return {}
    out = {}
    for zn, zt, c in zones:
        pr(f"{prefix}[{zn}] {zt}", f"{c:.1f} °C")
        out[zn] = c
    return out

def meminfo():
    d = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                p = line.split()
                if len(p) >= 2:
                    d[p[0].rstrip(":")] = int(p[1])
    except: pass
    return d

def mem_free_mb():
    return meminfo().get("MemFree", 0) // 1024

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
# SECTION 0 – SYSTEM INFO + THERMAL BASELINE
# ─────────────────────────────────────────────────────────
def s0_sysinfo():
    psec("SECTION 0 – SYSTEM INFO + THERMAL BASELINE")

    uname = os.uname()
    pr("Kernel",       uname.release)
    pr("Arch",         uname.machine)
    pr("MaixPy/maix",  "Available" if MAIX_OK else "NOT FOUND")
    pr("Python",       sys.version.split()[0])

    try:
        with open("/proc/loadavg") as f:
            pr("Load average", f.read().strip())
    except: pass

    mem = meminfo()
    total = mem.get("MemTotal", 0) // 1024
    avail = mem.get("MemAvailable", 0) // 1024
    pr("RAM Total",    f"{total} MB")
    pr("RAM Available",f"{avail} MB")

    # CPU freq
    for i in range(4):
        p = f"/sys/devices/system/cpu/cpu{i}/cpufreq/scaling_cur_freq"
        v = read_file(p)
        if v:
            pr(f"CPU{i} current freq", f"{int(v)//1000} MHz")
        p2 = f"/sys/devices/system/cpu/cpu{i}/cpufreq/cpuinfo_max_freq"
        v2 = read_file(p2)
        if v2:
            pr(f"CPU{i} max freq",     f"{int(v2)//1000} MHz")

    print()
    pr("── Thermal Baseline (idle) ──")
    baseline = log_temps("  ")
    return baseline


# ─────────────────────────────────────────────────────────
# SECTION 1 – MEMORY BANDWIDTH
# Mengukur throughput copy/read memory – bottleneck nyata
# ─────────────────────────────────────────────────────────
def s1_memory_bandwidth():
    psec("SECTION 1 – MEMORY BANDWIDTH")

    results = {}

    # ── 1a. bytearray copy bandwidth
    def bench_memcpy(block_mb, rounds):
        block = bytearray(block_mb * 1024 * 1024)
        dst   = bytearray(block_mb * 1024 * 1024)
        t = ts_ms()
        for _ in range(rounds):
            dst[:] = block
        elapsed_s = (ts_ms() - t) / 1000.0
        total_mb  = block_mb * rounds
        return elapsed_s, total_mb / elapsed_s

    # ── 1b. Sequential read bandwidth
    def bench_read(block_mb, rounds):
        block = bytearray(block_mb * 1024 * 1024)
        # fill
        for i in range(0, len(block), 4096):
            block[i] = i & 0xFF
        t = ts_ms()
        for _ in range(rounds):
            s = sum(block[i] for i in range(0, len(block), 64))  # stride read
        elapsed_s = (ts_ms() - t) / 1000.0
        total_mb  = block_mb * rounds
        return elapsed_s, total_mb / elapsed_s, s

    # ── 1c. maix.image memory – JPEG encode/decode as mem throughput proxy
    # (tested in section 2 separately)

    print()
    pr("bytearray copy 1MB x 100 rounds ...")
    try:
        e, bw = bench_memcpy(1, 100)
        pr("  Copy 1MB×100", f"{e*1000:.1f} ms total  |  {bw:.1f} MB/s")
        results["copy_1mb"] = bw
    except Exception as ex:
        pr("  ERROR", str(ex))

    print()
    pr("bytearray copy 4MB x 50 rounds ...")
    try:
        e, bw = bench_memcpy(4, 50)
        pr("  Copy 4MB×50",  f"{e*1000:.1f} ms total  |  {bw:.1f} MB/s")
        results["copy_4mb"] = bw
    except Exception as ex:
        pr("  ERROR", str(ex))

    print()
    pr("Sequential stride read 4MB x 20 rounds ...")
    try:
        e, bw, _ = bench_read(4, 20)
        pr("  Stride read 4MB×20", f"{e*1000:.1f} ms total  |  {bw:.1f} MB/s")
        results["stride_read"] = bw
    except Exception as ex:
        pr("  ERROR", str(ex))

    # ── maix image buffer bandwidth (if available)
    if MAIX_OK:
        print()
        pr("maix.image buffer copy benchmark (320x240 RGB, 500 iters)...")
        try:
            img = image.Image(320, 240, image.Format.FMT_RGB888)
            ITERS = 500
            t = ts_ms()
            for _ in range(ITERS):
                _ = img.to_bytes()
            elapsed = (ts_ms() - t) / 1000.0
            frame_bytes = 320 * 240 * 3
            total_mb = (ITERS * frame_bytes) / (1024**2)
            bw = total_mb / elapsed
            per_ms = elapsed * 1000 / ITERS
            pr("  to_bytes 320x240 RGB×500", f"{per_ms:.3f} ms/frame  |  {bw:.1f} MB/s")
            results["img_tobytes_320"] = bw
        except Exception as ex:
            pr("  ERROR", str(ex))

        print()
        pr("maix.image buffer copy benchmark (640x480 RGB, 200 iters)...")
        try:
            img = image.Image(640, 480, image.Format.FMT_RGB888)
            ITERS = 200
            t = ts_ms()
            for _ in range(ITERS):
                _ = img.to_bytes()
            elapsed = (ts_ms() - t) / 1000.0
            frame_bytes = 640 * 480 * 3
            total_mb = (ITERS * frame_bytes) / (1024**2)
            bw = total_mb / elapsed
            per_ms = elapsed * 1000 / ITERS
            pr("  to_bytes 640x480 RGB×200", f"{per_ms:.3f} ms/frame  |  {bw:.1f} MB/s")
            results["img_tobytes_640"] = bw
        except Exception as ex:
            pr("  ERROR", str(ex))

    print()
    pr("── Memory Bandwidth Summary ──")
    for k, v in results.items():
        pr(f"  {k}", f"{v:.1f} MB/s")

    return results


# ─────────────────────────────────────────────────────────
# SECTION 2 – JPEG CODEC THROUGHPUT
# JPEG encode adalah operasi kritis di AuralAI (500ms poll)
# dan di pipeline Context Mode (kirim ke OpenAI Vision)
# ─────────────────────────────────────────────────────────
def s2_jpeg_codec():
    psec("SECTION 2 – JPEG CODEC THROUGHPUT")
    pr("Relevan langsung ke AuralAI: JPEG encode untuk web dashboard")
    pr("polling dan Context Mode (upload ke OpenAI Vision API)")

    if not MAIX_OK:
        pr("SKIPPED – maix not available")
        return {}

    results = {}

    resolutions = [
        (320, 240,  "QVGA  320x240"),
        (640, 480,  "VGA   640x480"),
        (1280, 720, "HD   1280x720"),
    ]

    for w, h, label in resolutions:
        print()
        try:
            img_rgb = image.Image(w, h, image.Format.FMT_RGB888)
            # fill with gradient so JPEG has something to compress
            img_rgb.draw_rect(0, 0, w//2, h//2, image.Color.from_rgb(255, 64, 32), thickness=-1)
            img_rgb.draw_rect(w//2, 0, w//2, h//2, image.Color.from_rgb(32, 255, 64), thickness=-1)
            img_rgb.draw_rect(0, h//2, w//2, h//2, image.Color.from_rgb(64, 32, 255), thickness=-1)

            ITERS = 200 if w <= 640 else 50

            # Encode: RGB → JPEG
            t = ts_ms()
            for _ in range(ITERS):
                img_jpg = img_rgb.to_format(image.Format.FMT_JPEG)
            enc_ms = (ts_ms() - t) / ITERS

            # Get compressed size
            try:
                jpg_bytes = img_jpg.to_bytes()
                jpg_kb = len(jpg_bytes) / 1024.0
            except:
                jpg_kb = 0

            enc_fps = 1000.0 / enc_ms

            # Decode: JPEG → RGB  (via from_bytes if available)
            try:
                raw_jpg = img_jpg.to_bytes()
                t = ts_ms()
                for _ in range(ITERS):
                    img_back = image.from_bytes(w, h, image.Format.FMT_JPEG, raw_jpg)
                    img_back.to_format(image.Format.FMT_RGB888)
                dec_ms = (ts_ms() - t) / ITERS
                dec_fps = 1000.0 / dec_ms
            except Exception as de:
                dec_ms  = None
                dec_fps = None

            pr(f"{label}")
            pr(f"  JPEG size (compressed)",    f"{jpg_kb:.1f} KB  (ratio: {w*h*3/1024/jpg_kb:.1f}x)" if jpg_kb else "N/A")
            pr(f"  Encode (RGB→JPEG)",         f"{enc_ms:.2f} ms/frame  |  {enc_fps:.1f} fps max")
            if dec_fps:
                pr(f"  Decode (JPEG→RGB)",     f"{dec_ms:.2f} ms/frame  |  {dec_fps:.1f} fps max")
            results[label] = {"enc_ms": enc_ms, "enc_fps": enc_fps, "jpg_kb": jpg_kb}

        except Exception as ex:
            pr(f"{label}", f"ERROR: {ex}")

    return results


# ─────────────────────────────────────────────────────────
# SECTION 3 – NPU INFERENCE BENCHMARK
# Ini yang penting: seberapa cepat NPU bisa inference YOLO
# Diukur dalam 3 kondisi:
#   3a. NPU-only (no camera, synthetic frame) – NPU ceiling
#   3b. Camera → NPU (with real capture) – real pipeline
#   3c. Sustained 200-frame NPU stress
# ─────────────────────────────────────────────────────────
def s3_npu_benchmark():
    psec("SECTION 3 – NPU INFERENCE BENCHMARK")

    if not MAIX_OK:
        pr("SKIPPED – maix not available"); return {}

    model_path, model_label = find_yolo_model()
    if not model_path:
        pr("No YOLO model found at /root/models/")
        pr("Download: https://maixhub.com/model/zoo/453  (YOLO11n)")
        pr("          https://maixhub.com/model/zoo/400  (YOLOv8n)")
        return {}

    pr(f"Model: {model_label}  ({model_path})")
    print()

    results = {}

    try:
        if   "yolo11" in model_path: detector = nn.YOLO11(model=model_path, dual_buff=True)
        elif "yolov8" in model_path: detector = nn.YOLOv8(model=model_path, dual_buff=True)
        else:                        detector = nn.YOLOv5(model=model_path, dual_buff=True)

        in_w  = detector.input_width()
        in_h  = detector.input_height()
        in_fmt= detector.input_format()
        pr("Model input",  f"{in_w}x{in_h}  fmt={in_fmt}")

        # ── 3a. Synthetic frame – NPU ceiling (no camera latency)
        pr(""); pr("── 3a. NPU ceiling (synthetic frame, no camera) ──")
        pr("Tujuan: isolasi kecepatan NPU murni tanpa jitter capture")
        synthetic = image.Image(in_w, in_h, image.Format.FMT_RGB888)
        synthetic.draw_rect(0, 0, in_w, in_h, image.Color.from_rgb(200, 150, 100), thickness=-1)
        synthetic.draw_circle(in_w//2, in_h//2, 40, image.Color.from_rgb(50, 200, 50), thickness=-1)

        WARMUP = 20
        for _ in range(WARMUP):
            _ = detector.detect(synthetic, conf_th=0.5, iou_th=0.45)

        ITERS = 200
        t = ts_ms()
        for _ in range(ITERS):
            objs = detector.detect(synthetic, conf_th=0.5, iou_th=0.45)
        elapsed = ts_ms() - t
        per_inf = elapsed / ITERS
        inf_fps = 1000.0 / per_inf

        pr(f"  {ITERS} inferences, total", f"{elapsed:.1f} ms")
        pr("  Per inference",              f"{per_inf:.2f} ms")
        pr("  NPU ceiling FPS",            f"{inf_fps:.1f} fps  ← NPU max throughput")
        results["npu_ceiling_fps"] = inf_fps
        results["npu_per_inf_ms"]  = per_inf

        # ── 3b. Camera + NPU pipeline
        pr(""); pr("── 3b. Camera → NPU pipeline (real capture) ──")
        pr("Tujuan: fps nyata ketika kamera jalan bersamaan NPU")
        try:
            cam = camera.Camera(in_w, in_h, in_fmt)
            # warmup
            for _ in range(10):
                img = cam.read()
                _ = detector.detect(img, conf_th=0.5, iou_th=0.45)

            FRAMES = 100
            t = ts_ms()
            for _ in range(FRAMES):
                img  = cam.read()
                objs = detector.detect(img, conf_th=0.5, iou_th=0.45)
            elapsed = ts_ms() - t
            pipe_fps  = FRAMES / (elapsed / 1000.0)
            per_frame = elapsed / FRAMES

            pr(f"  {FRAMES} frames, total",  f"{elapsed:.1f} ms")
            pr("  Per frame (cam+infer)",    f"{per_frame:.2f} ms")
            pr("  Pipeline FPS",             f"{pipe_fps:.1f} fps")
            pr("  Overhead vs NPU-only",     f"+{per_frame - per_inf:.2f} ms/frame  ({(per_frame/per_inf - 1)*100:.1f}% slower)")
            results["pipeline_fps"]     = pipe_fps
            results["pipeline_per_ms"]  = per_frame
            del cam

        except Exception as ex:
            pr("  Camera+NPU pipeline ERROR", str(ex))

        # ── 3c. Sustained 200-frame NPU – check if throttle terjadi
        pr(""); pr("── 3c. Sustained NPU (200 frames) – throttle check ──")
        pr("Apakah NPU throttle setelah panas? Dibagi 4 batch @50 frame")
        try:
            cam2 = camera.Camera(in_w, in_h, in_fmt)
            batch_results = []
            for b in range(4):
                t = ts_ms()
                for _ in range(50):
                    img  = cam2.read()
                    objs = detector.detect(img, conf_th=0.5, iou_th=0.45)
                batch_ms  = ts_ms() - t
                batch_fps = 50 / (batch_ms / 1000.0)
                batch_results.append(batch_fps)
                temps = read_temps()
                temp_str = "  ".join(f"{zt}={c:.1f}°C" for _, zt, c in temps)
                pr(f"  Batch {b+1}/4 (frames {b*50+1}–{(b+1)*50})",
                   f"{batch_fps:.1f} fps  |  {temp_str or 'N/A'}")
            del cam2

            if batch_results:
                drop = batch_results[0] - batch_results[-1]
                pr("  FPS drop (batch1 → batch4)", f"{drop:.2f} fps  {'(throttle detected!)' if drop > 2 else '(stable)'}")
                results["npu_throttle_drop_fps"] = drop

        except Exception as ex:
            pr("  Sustained NPU ERROR", str(ex))

        print()
        log_temps("Post-NPU  ")

        del detector

    except Exception as ex:
        import traceback
        pr("SECTION 3 ERROR", str(ex))
        traceback.print_exc()

    return results


# ─────────────────────────────────────────────────────────
# SECTION 4 – FULL PIPELINE: Camera → NPU → JPEG encode
# Ini throughput nyata AuralAI Explorer Mode:
#   frame captured → YOLO infer → annotate → JPEG encode → kirim
# ─────────────────────────────────────────────────────────
def s4_full_pipeline():
    psec("SECTION 4 – FULL PIPELINE: Cam → NPU → Annotate → JPEG")
    pr("Mensimulasikan AuralAI Explorer Mode loop penuh")

    if not MAIX_OK:
        pr("SKIPPED – maix not available"); return {}

    model_path, model_label = find_yolo_model()
    if not model_path:
        pr("SKIPPED – no YOLO model"); return {}

    results = {}
    try:
        if   "yolo11" in model_path: detector = nn.YOLO11(model=model_path, dual_buff=True)
        elif "yolov8" in model_path: detector = nn.YOLOv8(model=model_path, dual_buff=True)
        else:                        detector = nn.YOLOv5(model=model_path, dual_buff=True)

        in_w = detector.input_width()
        in_h = detector.input_height()
        cam  = camera.Camera(in_w, in_h, detector.input_format())

        # warmup
        for _ in range(10):
            img = cam.read()
            _ = detector.detect(img, conf_th=0.5, iou_th=0.45)

        FRAMES = 100
        times = {"capture":[], "infer":[], "annotate":[], "jpeg":[]}

        for _ in range(FRAMES):
            t0 = ts_ms()
            img  = cam.read()
            t1 = ts_ms()
            objs = detector.detect(img, conf_th=0.5, iou_th=0.45)
            t2 = ts_ms()
            # annotate
            for obj in objs:
                img.draw_rect(obj.x, obj.y, obj.w, obj.h,
                              image.Color.from_rgb(255, 0, 0))
                lbl = detector.labels[obj.class_id] if hasattr(detector,'labels') else str(obj.class_id)
                img.draw_string(obj.x, obj.y, f"{lbl}:{obj.score:.2f}",
                                image.Color.from_rgb(255, 255, 0))
            t3 = ts_ms()
            # JPEG encode
            _ = img.to_format(image.Format.FMT_JPEG)
            t4 = ts_ms()

            times["capture" ].append(t1 - t0)
            times["infer"   ].append(t2 - t1)
            times["annotate"].append(t3 - t2)
            times["jpeg"    ].append(t4 - t3)

        def avg(lst): return sum(lst) / len(lst)

        cap_ms  = avg(times["capture"])
        inf_ms  = avg(times["infer"])
        ann_ms  = avg(times["annotate"])
        jpg_ms  = avg(times["jpeg"])
        total_ms= cap_ms + inf_ms + ann_ms + jpg_ms
        fps     = 1000.0 / total_ms

        print()
        pr("Step breakdown (avg per frame):")
        pr("  1. Camera capture",   f"{cap_ms:.2f} ms  ({cap_ms/total_ms*100:.1f}%)")
        pr("  2. NPU inference",    f"{inf_ms:.2f} ms  ({inf_ms/total_ms*100:.1f}%)")
        pr("  3. Annotate (draw)",  f"{ann_ms:.2f} ms  ({ann_ms/total_ms*100:.1f}%)")
        pr("  4. JPEG encode",      f"{jpg_ms:.2f} ms  ({jpg_ms/total_ms*100:.1f}%)")
        pr("  ─────────────────────────────────────────────")
        pr("  TOTAL per frame",     f"{total_ms:.2f} ms")
        pr("  End-to-end FPS",      f"{fps:.1f} fps")
        pr("  Latency to client",   f"{total_ms:.0f} ms / frame (worst-case)")

        results = {
            "cap_ms": cap_ms, "inf_ms": inf_ms,
            "ann_ms": ann_ms, "jpg_ms": jpg_ms,
            "total_ms": total_ms, "fps": fps
        }

        # Max objects detected in a frame
        pr(""); pr("Peak-latency frames (slowest 5%):")
        total_per_frame = [
            times["capture"][i]+times["infer"][i]+times["annotate"][i]+times["jpeg"][i]
            for i in range(FRAMES)
        ]
        sorted_t = sorted(total_per_frame, reverse=True)
        top5 = sorted_t[:5]
        pr("  Slowest 5 frames",    "  ".join(f"{v:.1f}ms" for v in top5))
        pr("  p95 latency",         f"{sorted_t[int(FRAMES*0.05)]:.2f} ms")
        pr("  p99 latency",         f"{sorted_t[0]:.2f} ms  (worst)")

        del cam
        del detector

    except Exception as ex:
        import traceback
        pr("SECTION 4 ERROR", str(ex))
        traceback.print_exc()

    return results


# ─────────────────────────────────────────────────────────
# SECTION 5 – CONCURRENT STRESS: AI loop + Web server
# Mensimulasikan arsitektur 2-thread AuralAI:
#   Thread A: camera + YOLO (AI loop)
#   Thread B: JPEG encode + HTTP-like response (web server)
# Ukurannya: apakah fps AI loop turun saat web thread aktif?
# ─────────────────────────────────────────────────────────
def s5_concurrent_stress():
    psec("SECTION 5 – CONCURRENT STRESS: AI Thread + Web Thread")
    pr("Simulasi arsitektur AuralAI: 2-thread model")
    pr("Thread-A = AI loop (cam + YOLO), Thread-B = web server (JPEG poll)")

    if not MAIX_OK:
        pr("SKIPPED – maix not available"); return {}

    model_path, model_label = find_yolo_model()
    if not model_path:
        pr("SKIPPED – no YOLO model"); return {}

    results = {}

    # ── 5a. Baseline: AI loop singlethreaded dulu
    pr(""); pr("── 5a. Baseline AI loop (single-thread, no web server) ──")
    try:
        if   "yolo11" in model_path: det_a = nn.YOLO11(model=model_path, dual_buff=True)
        elif "yolov8" in model_path: det_a = nn.YOLOv8(model=model_path, dual_buff=True)
        else:                        det_a = nn.YOLOv5(model=model_path, dual_buff=True)

        cam_a = camera.Camera(det_a.input_width(), det_a.input_height(), det_a.input_format())
        for _ in range(10):
            img = cam_a.read(); _ = det_a.detect(img)

        FRAMES = 60
        t = ts_ms()
        for _ in range(FRAMES):
            img = cam_a.read(); _ = det_a.detect(img, conf_th=0.5, iou_th=0.45)
        elapsed = ts_ms() - t
        solo_fps = FRAMES / (elapsed / 1000.0)
        pr("  AI loop solo FPS", f"{solo_fps:.1f} fps  (baseline)")
        results["solo_fps"] = solo_fps
        del cam_a, det_a
        gc.collect()
        time.sleep(0.5)

    except Exception as ex:
        pr("  Baseline ERROR", str(ex))
        solo_fps = None

    # ── 5b. Concurrent: AI loop + web server thread simultaneous
    pr(""); pr("── 5b. Concurrent AI + Web thread ──")
    try:
        if   "yolo11" in model_path: det_b = nn.YOLO11(model=model_path, dual_buff=True)
        elif "yolov8" in model_path: det_b = nn.YOLOv8(model=model_path, dual_buff=True)
        else:                        det_b = nn.YOLOv5(model=model_path, dual_buff=True)

        cam_b = camera.Camera(det_b.input_width(), det_b.input_height(), det_b.input_format())

        # Shared state (mimicking AuralAI shared frame buffer)
        shared = {
            "frame":    None,
            "lock":     threading.Lock(),
            "running":  True,
            "web_fps":  0,
            "web_count":0,
        }

        # Web server thread: reads shared frame, JPEG-encodes it, simulates HTTP response
        def web_server_thread():
            count = 0
            t_start = ts_ms()
            while shared["running"]:
                with shared["lock"]:
                    frame = shared["frame"]
                if frame is not None:
                    try:
                        # Simulate: JPEG encode + fake HTTP response serialization
                        jpg = frame.to_format(image.Format.FMT_JPEG)
                        payload = jpg.to_bytes() if jpg else b""
                        # Simulate HTTP header construction
                        header = (f"HTTP/1.1 200 OK\r\n"
                                  f"Content-Type: image/jpeg\r\n"
                                  f"Content-Length: {len(payload)}\r\n\r\n").encode()
                        _ = header + payload  # simulate send
                        count += 1
                    except:
                        pass
                time.sleep(0.0)  # yield

            elapsed_s = (ts_ms() - t_start) / 1000.0
            shared["web_fps"]   = count / elapsed_s if elapsed_s > 0 else 0
            shared["web_count"] = count

        # Start web thread
        wt = threading.Thread(target=web_server_thread, daemon=True)
        wt.start()

        # AI loop in main thread
        FRAMES = 60
        t = ts_ms()
        for _ in range(FRAMES):
            img  = cam_b.read()
            objs = det_b.detect(img, conf_th=0.5, iou_th=0.45)
            # Update shared frame (atomic swap)
            with shared["lock"]:
                shared["frame"] = img.copy()
        elapsed = ts_ms() - t

        # Stop web thread
        shared["running"] = False
        wt.join(timeout=2.0)

        concurrent_fps = FRAMES / (elapsed / 1000.0)
        web_fps        = shared["web_fps"]
        web_count      = shared["web_count"]

        pr("  AI loop concurrent FPS", f"{concurrent_fps:.1f} fps")
        pr("  Web thread encode rate",  f"{web_fps:.1f} JPEG/s  ({web_count} total)")
        if solo_fps:
            delta = solo_fps - concurrent_fps
            pct   = delta / solo_fps * 100
            pr("  AI FPS degradation",
               f"{delta:.2f} fps  ({pct:.1f}%)  {'(significant!)' if pct > 10 else '(acceptable)'}")
        results["concurrent_fps"] = concurrent_fps
        results["web_thread_fps"] = web_fps

        del cam_b, det_b
        gc.collect()

    except Exception as ex:
        import traceback
        pr("  Concurrent stress ERROR", str(ex))
        traceback.print_exc()

    print()
    log_temps("Post-concurrent  ")

    return results


# ─────────────────────────────────────────────────────────
# SECTION 6 – THERMAL ENDURANCE (90s full pipeline)
# Log suhu tiap 15 detik, track peak per zone
# Ukur apakah ada thermal throttle (fps turun seiring panas)
# ─────────────────────────────────────────────────────────
def s6_thermal_endurance():
    psec("SECTION 6 – THERMAL ENDURANCE (90s full pipeline)")
    pr("Full pipeline: Cam + YOLO + Annotate + JPEG encode")
    pr("Suhu & fps dicatat tiap 15 detik untuk deteksi throttle")

    DURATION_S   = 90
    LOG_INTERVAL = 15

    if not MAIX_OK:
        pr("Fallback: CPU-only burn (no maix)")
        _cpu_only_endurance(DURATION_S, LOG_INTERVAL)
        return {}

    model_path, _ = find_yolo_model()
    if not model_path:
        pr("No YOLO model – running camera + ImgOps only")
        _camera_imgops_endurance(DURATION_S, LOG_INTERVAL)
        return {}

    try:
        if   "yolo11" in model_path: detector = nn.YOLO11(model=model_path, dual_buff=True)
        elif "yolov8" in model_path: detector = nn.YOLOv8(model=model_path, dual_buff=True)
        else:                        detector = nn.YOLOv5(model=model_path, dual_buff=True)

        cam = camera.Camera(detector.input_width(), detector.input_height(),
                            detector.input_format())
        # warmup
        for _ in range(10):
            _ = detector.detect(cam.read())

    except Exception as ex:
        pr("Init ERROR", str(ex))
        return {}

    max_temps  = {}
    fps_log    = []          # (t, fps) tuples
    frame_count= 0
    t_start    = ts()
    t_end      = ts() + DURATION_S
    t_log      = ts() + LOG_INTERVAL
    window_start= ts()
    window_frames= 0

    print()
    pr("t=0s  Starting endurance loop...")

    while ts() < t_end:
        img  = cam.read()
        objs = detector.detect(img, conf_th=0.5, iou_th=0.45)
        for obj in objs:
            img.draw_rect(obj.x, obj.y, obj.w, obj.h, image.Color.from_rgb(255, 0, 0))
        _ = img.to_format(image.Format.FMT_JPEG)

        frame_count   += 1
        window_frames += 1

        if ts() >= t_log:
            elapsed    = ts() - t_start
            window_s   = ts() - window_start
            window_fps = window_frames / window_s if window_s > 0 else 0
            total_fps  = frame_count / elapsed   if elapsed   > 0 else 0
            mem_mb     = mem_free_mb()

            fps_log.append((elapsed, window_fps))

            print()
            pr(f"  ── t={elapsed:.0f}s ──")
            pr("    Window FPS (last 15s)", f"{window_fps:.1f} fps")
            pr("    Cumulative FPS",        f"{total_fps:.1f} fps")
            pr("    Frames total",          str(frame_count))
            pr("    RAM free",              f"{mem_mb} MB")
            temps = read_temps()
            for zn, zt, c in temps:
                pr(f"    [{zn}] {zt}",      f"{c:.1f} °C")
                if zn not in max_temps or c > max_temps[zn][0]:
                    max_temps[zn] = (c, elapsed)

            t_log         = ts() + LOG_INTERVAL
            window_start  = ts()
            window_frames = 0

    total_elapsed = ts() - t_start
    avg_fps       = frame_count / total_elapsed

    print()
    print(DIV2)
    pr("Endurance complete")
    pr("Total frames",    str(frame_count))
    pr("Avg FPS overall", f"{avg_fps:.1f} fps")

    if fps_log and len(fps_log) >= 2:
        first_fps = fps_log[0][1]
        last_fps  = fps_log[-1][1]
        drop      = first_fps - last_fps
        pr("FPS at t=15s",   f"{first_fps:.1f} fps")
        pr("FPS at t=end",   f"{last_fps:.1f} fps")
        pr("FPS drift",
           f"{drop:+.2f} fps  {'← thermal throttle!' if drop > 3 else '← stable (no throttle)'}")

    print()
    pr("Peak temperatures:")
    for zn, (peak, t_at) in max_temps.items():
        pr(f"  [{zn}]", f"{peak:.1f} °C  (at t={t_at:.0f}s)")

    del cam, detector
    return {"avg_fps": avg_fps, "max_temps": max_temps, "fps_log": fps_log}


def _cpu_only_endurance(dur, interval):
    """Fallback endurance when maix unavailable."""
    t_end = ts() + dur
    t_log = ts() + interval
    iters = 0
    t0    = ts()
    while ts() < t_end:
        acc = 0.0
        for i in range(1, 5001):
            acc += math.sin(i * 0.01) * math.cos(i * 0.02)
        iters += 1
        if ts() >= t_log:
            pr(f"  t={ts()-t0:.0f}s  iters={iters}")
            log_temps("    ")
            t_log += interval

def _camera_imgops_endurance(dur, interval):
    """Camera + ImgOps endurance when no YOLO model."""
    try:
        cam = camera.Camera(320, 240)
    except Exception as ex:
        pr("Camera init failed", str(ex)); return
    t_end = ts() + dur
    t_log = ts() + interval
    frames= 0; t0 = ts()
    while ts() < t_end:
        img = cam.read()
        img.draw_rect(0, 0, 320, 240, image.Color.from_rgb(255, 0, 0), thickness=2)
        for r in [30, 60, 90]:
            img.draw_circle(160, 120, r, image.Color.from_rgb(0, 255, 0))
        _ = img.to_format(image.Format.FMT_JPEG)
        frames += 1
        if ts() >= t_log:
            elapsed = ts() - t0
            pr(f"  t={elapsed:.0f}s  fps={frames/elapsed:.1f}")
            log_temps("    ")
            t_log += interval
    del cam


# ─────────────────────────────────────────────────────────
# SECTION 7 – FINAL REPORT
# ─────────────────────────────────────────────────────────
def s7_report(s1, s2, s3, s4, s5, s6):
    psec("SECTION 7 – FINAL REPORT")

    print()
    pr("── MEMORY BANDWIDTH ──")
    if s1:
        for k in ["copy_1mb","copy_4mb","stride_read","img_tobytes_640"]:
            if k in s1: pr(f"  {k}", f"{s1[k]:.1f} MB/s")
    else: pr("  No data")

    print()
    pr("── JPEG ENCODE THROUGHPUT ──")
    if s2:
        for label, v in s2.items():
            pr(f"  {label}",
               f"enc={v['enc_ms']:.2f}ms ({v['enc_fps']:.1f}fps)  size={v['jpg_kb']:.1f}KB")
    else: pr("  No data")

    print()
    pr("── NPU INFERENCE ──")
    if s3:
        if "npu_ceiling_fps"  in s3: pr("  NPU ceiling FPS",      f"{s3['npu_ceiling_fps']:.1f} fps")
        if "npu_per_inf_ms"   in s3: pr("  Per-inference latency", f"{s3['npu_per_inf_ms']:.2f} ms")
        if "pipeline_fps"     in s3: pr("  Camera+NPU pipeline",   f"{s3['pipeline_fps']:.1f} fps")
        if "npu_throttle_drop_fps" in s3:
            drop = s3["npu_throttle_drop_fps"]
            pr("  NPU throttle drop",     f"{drop:.2f} fps  {'(detected!)' if drop > 2 else '(none)'}")
    else: pr("  No data (model missing)")

    print()
    pr("── FULL PIPELINE (Cam→NPU→Annotate→JPEG) ──")
    if s4:
        pr("  Total latency/frame",  f"{s4.get('total_ms',0):.2f} ms")
        pr("  End-to-end FPS",       f"{s4.get('fps',0):.1f} fps")
        pr("  Bottleneck stage",
           max(
               [("capture",   s4.get("cap_ms",0)),
                ("NPU infer", s4.get("inf_ms",0)),
                ("annotate",  s4.get("ann_ms",0)),
                ("JPEG enc",  s4.get("jpg_ms",0))],
               key=lambda x: x[1]
           )[0])
    else: pr("  No data")

    print()
    pr("── CONCURRENCY (2-thread AuralAI pattern) ──")
    if s5:
        solo = s5.get("solo_fps")
        conc = s5.get("concurrent_fps")
        web  = s5.get("web_thread_fps")
        if solo and conc:
            pr("  Solo AI FPS",      f"{solo:.1f} fps")
            pr("  Concurrent AI FPS",f"{conc:.1f} fps")
            pr("  Web thread FPS",   f"{web:.1f} JPEG/s" if web else "N/A")
            pct = (solo - conc) / solo * 100
            pr("  AI perf penalty",  f"{pct:.1f}%  {'(acceptable < 10%)' if pct < 10 else '(consider tuning thread priority!)'}")
    else: pr("  No data")

    print()
    pr("── THERMAL ENDURANCE PEAKS ──")
    if s6 and "max_temps" in s6:
        for zn, (peak, t_at) in s6["max_temps"].items():
            pr(f"  [{zn}]", f"{peak:.1f} °C  @ t={t_at:.0f}s")
        if "fps_log" in s6 and s6["fps_log"]:
            first = s6["fps_log"][0][1]
            last  = s6["fps_log"][-1][1]
            pr("  Thermal throttle", f"{first:.1f}→{last:.1f} fps  (Δ{last-first:+.1f})")
    else:
        pr("  No data")
        pr("  Final idle temp:")
        log_temps("    ")

    print()
    print(DIV)
    print("  Benchmark complete.")
    print(DIV)


# ─────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────
def main():
    print(); print(DIV)
    print("  MaixCAM Proper Benchmark v2")
    print(f"  {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(DIV)

    s0_sysinfo()
    r1 = s1_memory_bandwidth()
    r2 = s2_jpeg_codec()
    r3 = s3_npu_benchmark()
    r4 = s4_full_pipeline()
    r5 = s5_concurrent_stress()
    r6 = s6_thermal_endurance()
    s7_report(r1, r2, r3, r4, r5, r6)

    print(f"\n  Done: {time.strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
    main()

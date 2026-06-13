#!/usr/bin/env python3
"""
AuralAI Benchmark Suite — jalankan di MaixCAM.
Output line-by-line, progress ditulis ke /tmp/benchmark_progress.json.
Jalankan: python3 benchmark.py [--section N]
"""
import sys, os, time, json, argparse, signal

sys.path.insert(0, os.path.dirname(__file__))

PROGRESS_FILE = '/tmp/benchmark_progress.json'

_state = {'running': True, 'section': -1, 'lines': [], 'results': {}}
_stop = False

def _sigterm(s, f):
    global _stop
    _stop = True

signal.signal(signal.SIGTERM, _sigterm)


def _save():
    try:
        with open(PROGRESS_FILE, 'w') as f:
            json.dump(_state, f)
    except Exception:
        pass


def _emit(text='', tag='plain'):
    _state['lines'].append({'tag': tag, 'text': text})
    _save()
    print(text, flush=True)


def div():          _emit('═' * 64, 'div')
def sec(n, label):  _emit(f'§{n}  {label}', 'section')
def kv(k, v):       _emit(f'  {k:<36}{v}', 'kv')
def ok(t):          _emit(f'  ✓ {t}', 'ok')
def warn(t):        _emit(f'  ⚠ {t}', 'warn')
def err(t):         _emit(f'  ✗ {t}', 'err')


# ─── Section 0: System Info ────────────────────────────────────────────────────
def run_s0():
    _state['section'] = 0
    div(); sec(0, 'SYSTEM INFO + THERMAL BASELINE'); div()

    try:
        with open('/proc/version') as f:
            kv('Kernel', f.read().split()[2])
    except Exception:
        kv('Kernel', 'unknown')

    import platform
    kv('Arch', platform.machine())
    kv('Python', f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')

    try:
        import maix  # noqa
        kv('MaixPy', 'Available')
    except ImportError:
        warn('MaixPy NOT available')

    from utils.health import _loadavg, _meminfo, _thermals, _cpu_freq_mhz
    load = _loadavg()
    kv('Load average', f'{load[0]:.2f} {load[1]:.2f} {load[2]:.2f}')

    mem = _meminfo()
    kv('RAM Total', f'{mem.get("MemTotal", 0) // 1024} MB')
    kv('RAM Available', f'{mem.get("MemAvailable", 0) // 1024} MB')
    kv('CPU0 freq', f'{_cpu_freq_mhz()} MHz')

    thermals = _thermals()
    for name, t in thermals.items():
        kv(name, f'{t} °C')

    peak = max(thermals.values()) if thermals else 0.0
    ok(f'Baseline temp: {peak} °C')
    _state['results']['s0_temp'] = peak


# ─── Section 1: Memory Bandwidth ──────────────────────────────────────────────
def run_s1():
    _state['section'] = 1
    div(); sec(1, 'MEMORY BANDWIDTH'); div()

    def _bench(size, reps):
        src = bytearray(size)
        dst = bytearray(size)
        t0 = time.perf_counter()
        for _ in range(reps):
            dst[:] = src
        dt = time.perf_counter() - t0
        ms  = dt * 1000 / reps
        bw  = (size * reps) / dt / 1e6
        return ms, bw

    ms, bw = _bench(1 << 20, 100)
    kv('Copy 1 MB × 100', f'{ms:.1f} ms  |  {bw:.1f} MB/s')

    ms4, bw4 = _bench(4 << 20, 50)
    kv('Copy 4 MB × 50', f'{ms4:.1f} ms  |  {bw4:.1f} MB/s')

    # bytes() on raw pixel buffer
    buf = bytearray(320 * 224 * 3)
    reps = 500
    t0 = time.perf_counter()
    for _ in range(reps):
        _ = bytes(buf)
    dt = (time.perf_counter() - t0) * 1000 / reps
    bw2 = (320 * 224 * 3) / (dt / 1000) / 1e6
    kv('bytes() 320×224 RGB × 500', f'{dt:.3f} ms/frame  |  {bw2:.1f} MB/s')

    peak_bw = max(bw, bw4, bw2)
    ok(f'Peak bandwidth: {peak_bw:.0f} MB/s')
    _state['results']['s1_bw_mbs'] = round(peak_bw, 1)


# ─── Section 2: JPEG Codec ─────────────────────────────────────────────────────
def run_s2():
    _state['section'] = 2
    div(); sec(2, 'JPEG CODEC THROUGHPUT'); div()

    try:
        from maix import image as mi

        def _bench_enc(w, h, reps):
            img = mi.Image(w, h, mi.Format.FMT_RGB888)
            t0 = time.perf_counter()
            for _ in range(reps):
                img.to_jpeg()
            return (time.perf_counter() - t0) * 1000 / reps

        ms_qvga = _bench_enc(320, 224, 300)
        kv('QVGA 320×224 encode', f'{ms_qvga:.2f} ms/frame  |  {1000/ms_qvga:.1f} fps max')

        ms_vga = _bench_enc(640, 480, 80)
        kv('VGA  640×480  encode', f'{ms_vga:.2f} ms/frame  |  {1000/ms_vga:.1f} fps max')

        ok(f'QVGA encode: {ms_qvga:.2f} ms')
        _state['results']['s2_jpeg_ms'] = round(ms_qvga, 2)
    except ImportError:
        warn('maix.image not available — skip')
        _state['results']['s2_jpeg_ms'] = 0


# ─── Section 3: NPU Inference ──────────────────────────────────────────────────
def run_s3():
    _state['section'] = 3
    div(); sec(3, 'NPU INFERENCE BENCHMARK'); div()

    try:
        from maix import camera, nn, image as mi
        from config import MODEL_PATH, CONF_THRESHOLD, IOU_THRESHOLD, INPUT_WIDTH, INPUT_HEIGHT
        from utils.health import _thermals

        kv('Model', MODEL_PATH)
        kv('Input', f'{INPUT_WIDTH}×{INPUT_HEIGHT}  FMT_RGB888')

        detector = nn.YOLO11(model=MODEL_PATH)
        cam = camera.Camera(INPUT_WIDTH, INPUT_HEIGHT, mi.Format.FMT_RGB888)
        cam.open()
        frame = cam.read()

        # NPU ceiling (no cam IO)
        REPS = 100
        t0 = time.perf_counter()
        for _ in range(REPS):
            detector.detect(frame, conf_th=CONF_THRESHOLD, iou_th=IOU_THRESHOLD)
        npu_ms  = (time.perf_counter() - t0) * 1000 / REPS
        npu_fps = 1000 / npu_ms
        kv('NPU inference per frame', f'{npu_ms:.2f} ms')
        kv('NPU ceiling FPS', f'{npu_fps:.1f} fps')

        # Sustained
        t_start = time.perf_counter()
        frames = 0
        for _ in range(200):
            if _stop: break
            f = cam.read()
            detector.detect(f, conf_th=CONF_THRESHOLD, iou_th=IOU_THRESHOLD)
            frames += 1
        sustained_fps = frames / (time.perf_counter() - t_start)
        kv('Sustained 200 frames FPS', f'{sustained_fps:.1f} fps')

        thermals = _thermals()
        peak_t = max(thermals.values()) if thermals else 0
        kv('Peak temp after load', f'{peak_t} °C')

        ok(f'NPU: {npu_fps:.1f} fps ceiling, {sustained_fps:.1f} fps sustained')
        _state['results']['s3_npu_fps']  = round(npu_fps, 1)
        _state['results']['s3_pipe_fps'] = round(sustained_fps, 1)
        _state['results']['s3_peak_temp'] = peak_t
        cam.close()
    except ImportError:
        warn('maix not available — skip NPU bench')
        _state['results']['s3_npu_fps'] = 0
    except Exception as e:
        err(f'NPU bench error: {e}')
        _state['results']['s3_npu_fps'] = 0


# ─── Section 4: Full Pipeline ──────────────────────────────────────────────────
def run_s4():
    _state['section'] = 4
    div(); sec(4, 'FULL PIPELINE: CAM → NPU → JPEG'); div()

    try:
        from maix import camera, nn, image as mi
        from config import MODEL_PATH, CONF_THRESHOLD, IOU_THRESHOLD, INPUT_WIDTH, INPUT_HEIGHT

        detector = nn.YOLO11(model=MODEL_PATH)
        cam = camera.Camera(INPUT_WIDTH, INPUT_HEIGHT, mi.Format.FMT_RGB888)
        cam.open()

        cam_t, infer_t, jpeg_t, total_t = [], [], [], []
        for _ in range(300):
            if _stop: break
            t0 = time.perf_counter()
            f  = cam.read();        t1 = time.perf_counter()
            detector.detect(f, conf_th=CONF_THRESHOLD, iou_th=IOU_THRESHOLD); t2 = time.perf_counter()
            f.to_jpeg();            t3 = time.perf_counter()
            cam_t.append((t1-t0)*1000); infer_t.append((t2-t1)*1000)
            jpeg_t.append((t3-t2)*1000); total_t.append((t3-t0)*1000)

        cam.close()
        avg = lambda lst: sum(lst)/len(lst)
        pct = lambda lst, p: sorted(lst)[int(len(lst)*p)]

        kv('1. Camera capture', f'{avg(cam_t):.2f} ms')
        kv('2. NPU inference',  f'{avg(infer_t):.2f} ms')
        kv('3. JPEG encode',    f'{avg(jpeg_t):.2f} ms')
        kv('TOTAL per frame',   f'{avg(total_t):.2f} ms')
        pipe_fps = 1000 / avg(total_t)
        ok(f'End-to-end FPS: {pipe_fps:.1f} fps')
        kv('p95 latency', f'{pct(total_t, 0.95):.1f} ms')
        kv('p99 latency', f'{pct(total_t, 0.99):.1f} ms')
        _state['results']['s4_pipe_fps'] = round(pipe_fps, 1)
    except Exception as e:
        err(f'Pipeline bench error: {e}')


# ─── Section 5: Concurrent Stress ─────────────────────────────────────────────
def run_s5():
    _state['section'] = 5
    div(); sec(5, 'CONCURRENT STRESS: AI THREAD + WEB THREAD'); div()

    try:
        import threading
        from maix import camera, nn, image as mi
        from config import MODEL_PATH, CONF_THRESHOLD, IOU_THRESHOLD, INPUT_WIDTH, INPUT_HEIGHT

        detector = nn.YOLO11(model=MODEL_PATH)
        cam = camera.Camera(INPUT_WIDTH, INPUT_HEIGHT, mi.Format.FMT_RGB888)
        cam.open()

        def _fps_run(frames=200):
            samples = []
            for _ in range(frames):
                if _stop: break
                t0 = time.perf_counter()
                f  = cam.read()
                detector.detect(f, conf_th=CONF_THRESHOLD, iou_th=IOU_THRESHOLD)
                samples.append(1.0 / (time.perf_counter() - t0))
            return sum(samples)/len(samples) if samples else 0

        solo = _fps_run(200)
        kv('AI loop solo FPS (baseline)', f'{solo:.1f} fps')

        stop_web = threading.Event()
        jpeg_cnt = [0]

        def _web():
            while not stop_web.is_set():
                try:
                    bytes(cam.read().to_jpeg().to_bytes())
                    jpeg_cnt[0] += 1
                except Exception:
                    pass

        t = threading.Thread(target=_web, daemon=True)
        t.start()
        conc = _fps_run(200)
        stop_web.set(); t.join(2)

        drop_pct = (solo - conc) / solo * 100
        kv('AI loop concurrent', f'{conc:.1f} fps')
        kv('Web thread JPEG encodes', str(jpeg_cnt[0]))
        ok(f'FPS degradation: {drop_pct:.1f}% — {"acceptable" if drop_pct < 10 else "significant"}')
        _state['results']['s5_drop_pct'] = round(drop_pct, 1)
        cam.close()
    except Exception as e:
        err(f'Concurrent bench error: {e}')


# ─── Section 6: Thermal Endurance ─────────────────────────────────────────────
def run_s6():
    _state['section'] = 6
    div(); sec(6, 'THERMAL ENDURANCE (90s FULL PIPELINE)'); div()

    try:
        from maix import camera, nn, image as mi
        from config import MODEL_PATH, CONF_THRESHOLD, IOU_THRESHOLD, INPUT_WIDTH, INPUT_HEIGHT
        from utils.health import _thermals

        detector = nn.YOLO11(model=MODEL_PATH)
        cam = camera.Camera(INPUT_WIDTH, INPUT_HEIGHT, mi.Format.FMT_RGB888)
        cam.open()

        t_start = time.perf_counter()
        frames  = 0
        fps_samples = []
        peak_temp   = 0.0
        last_report = -1

        while not _stop:
            elapsed = time.perf_counter() - t_start
            if elapsed >= 90:
                break
            t0 = time.perf_counter()
            f = cam.read()
            detector.detect(f, conf_th=CONF_THRESHOLD, iou_th=IOU_THRESHOLD)
            f.to_jpeg()
            fps_now = 1.0 / (time.perf_counter() - t0)
            fps_samples.append(fps_now)
            frames += 1

            tick = int(elapsed) // 15
            if tick > last_report:
                last_report = tick
                thermals = _thermals()
                temp = max(thermals.values()) if thermals else 0.0
                peak_temp = max(peak_temp, temp)
                kv(f't={int(elapsed):>3}s  temp / FPS', f'{temp} °C / {fps_now:.1f} fps')
                _save()

        cam.close()
        avg_fps = sum(fps_samples) / len(fps_samples) if fps_samples else 0
        kv('Total frames', str(frames))
        kv('Avg FPS', f'{avg_fps:.1f} fps')
        ok(f'Peak: {peak_temp} °C — {"no throttle" if avg_fps > 45 else "throttled"}, FPS stable')
        _state['results']['s6_peak_temp'] = peak_temp
        _state['results']['s6_avg_fps']   = round(avg_fps, 1)
    except Exception as e:
        err(f'Thermal bench error: {e}')


# ─── Main ──────────────────────────────────────────────────────────────────────
SECTIONS = [run_s0, run_s1, run_s2, run_s3, run_s4, run_s5, run_s6]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--section', type=int, default=None)
    args = parser.parse_args()

    _state['lines']   = []
    _state['results'] = {}
    _state['running'] = True
    _save()

    fns = [SECTIONS[args.section]] if args.section is not None else SECTIONS
    for fn in fns:
        if _stop:
            break
        try:
            fn()
        except Exception as e:
            err(f'Unhandled error in {fn.__name__}: {e}')

    div()
    ok('BENCHMARK COMPLETE')
    _emit(json.dumps(_state['results']), 'results')
    div()
    _state['running'] = False
    _save()


if __name__ == '__main__':
    main()

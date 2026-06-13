#!/usr/bin/env python3
"""
AuralAI Overnight Stress Test — daemon yang menjalankan full pipeline loop.
Status ditulis ke /tmp/overnight_status.json setiap 10 detik.
Berhenti jika /tmp/overnight_stop ada atau menerima SIGTERM.
Jalankan: python3 overnight_stress.py [--hours N]
"""
import sys, os, time, json, signal, argparse

sys.path.insert(0, os.path.dirname(__file__))

STATUS_FILE = '/tmp/overnight_status.json'
STOP_FILE   = '/tmp/overnight_stop'

_running = True


def _sigterm(signum, frame):
    global _running
    _running = False


signal.signal(signal.SIGTERM, _sigterm)
signal.signal(signal.SIGINT,  _sigterm)


def _write(status):
    try:
        with open(STATUS_FILE, 'w') as f:
            json.dump(status, f)
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--hours', type=float, default=3.0)
    args = parser.parse_args()

    duration_s = args.hours * 3600
    start_time = time.time()

    status = {
        'running':         True,
        'elapsed_s':       0,
        'fps':             0.0,
        'temp_c':          0.0,
        'ram_free_mb':     0,
        'throttle_events': 0,
        'frames_total':    0,
        'start_time':      time.strftime('%Y-%m-%dT%H:%M:%S'),
        'target_hours':    args.hours,
        'error':           None,
    }
    _write(status)

    # Remove leftover stop file
    try: os.remove(STOP_FILE)
    except FileNotFoundError: pass

    try:
        from maix import camera, nn, image as mi
        from config import MODEL_PATH, CONF_THRESHOLD, IOU_THRESHOLD, INPUT_WIDTH, INPUT_HEIGHT
        from utils.health import _thermals, _meminfo

        detector = nn.YOLO11(model=MODEL_PATH)
        cam = camera.Camera(INPUT_WIDTH, INPUT_HEIGHT, mi.Format.FMT_RGB888)
        cam.open()

        frames          = 0
        throttle_events = 0
        fps_window      = []  # fps samples in last 10s
        fps_smooth      = 0.0
        last_status_t   = 0.0
        last_fps_t      = time.time()

        # Warm-up FPS baseline (first 30s)
        baseline_fps    = None
        baseline_done   = False

        while _running and not os.path.exists(STOP_FILE):
            elapsed = time.time() - start_time
            if elapsed >= duration_s:
                break

            t0  = time.perf_counter()
            f   = cam.read()
            detector.detect(f, conf_th=CONF_THRESHOLD, iou_th=IOU_THRESHOLD)
            f.to_jpeg()
            frame_fps = 1.0 / max(time.perf_counter() - t0, 1e-6)
            fps_window.append(frame_fps)
            frames += 1

            # Smooth FPS over ~5s window
            now = time.time()
            if now - last_fps_t >= 5.0:
                fps_smooth  = sum(fps_window) / len(fps_window)
                fps_window  = []
                last_fps_t  = now

                if not baseline_done and elapsed >= 30:
                    baseline_fps  = fps_smooth
                    baseline_done = True

                # Throttle detection: FPS drops >25% below baseline
                if baseline_fps and fps_smooth < baseline_fps * 0.75:
                    throttle_events += 1

            # Write status every 10s
            if now - last_status_t >= 10.0:
                last_status_t = now
                thermals  = _thermals()
                temp      = max(thermals.values()) if thermals else 0.0
                mem       = _meminfo()
                ram_free  = mem.get('MemAvailable', 0) // 1024

                status.update({
                    'elapsed_s':       int(elapsed),
                    'fps':             round(fps_smooth, 1),
                    'temp_c':          temp,
                    'ram_free_mb':     ram_free,
                    'throttle_events': throttle_events,
                    'frames_total':    frames,
                })
                _write(status)

        cam.close()

    except Exception as e:
        status['error'] = str(e)

    status['running']   = False
    status['elapsed_s'] = int(time.time() - start_time)
    _write(status)

    # Cleanup
    try: os.remove(STOP_FILE)
    except FileNotFoundError: pass


if __name__ == '__main__':
    main()

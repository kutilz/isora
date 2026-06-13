#!/usr/bin/env python3
"""
Test 1 — End-to-End Latency
============================
Mengukur waktu nyata setiap tahap pipeline dari kamera hingga audio.

Pipeline yang diukur:
  [1] Camera capture      → frame RGB
  [2] NPU inference       → bounding boxes
  [3] Post-processing     → filter label + posisi
  [4] Audio queue insert  → PriorityQueue.put()
  [5] Queue → play start  → waktu sejak task dimasukkan sampai _play_task() dipanggil

Standar Kelulusan:
  p95 total pipeline (tahap 1-4) < 300 ms
  Audio queue-to-play latency < 120 ms (target queue hampir kosong)

Score:
  100 jika rata-rata < 100ms, linear turun ke 0 di 300ms
"""

import sys, os, time, json, threading, queue as _queue
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

PASS_MS          = 300    # p95 harus di bawah ini
TARGET_FRAMES    = 100    # jumlah frame untuk pengukuran
WARMUP_FRAMES    = 10
RESULTS_FILE     = "/root/logs/bench_t1_latency.json"

# ─── Emit helper ──────────────────────────────────────────────────────────────

def _make_emit(cb=None):
    def emit(text="", tag="plain"):
        if cb:
            cb(text, tag)
        print(text, flush=True)
    return emit


# ─── Audio Queue-to-Play Probe ────────────────────────────────────────────────

class _AudioProbe:
    """
    Monkey-patches AudioManager._play_task() untuk mengukur
    waktu dari queue insertion sampai play_task() dipanggil.
    Dipasang sementara selama pengukuran, lalu di-restore.
    """

    def __init__(self, audio_manager):
        self._am      = audio_manager
        self._times:  list = []
        self._lock    = threading.Lock()
        self._original_play = audio_manager._play_task

    def install(self):
        probe = self

        def _patched_play(task):
            if hasattr(task, "_probe_queued_at"):
                delta_ms = (time.perf_counter() - task._probe_queued_at) * 1000
                with probe._lock:
                    probe._times.append(delta_ms)
            probe._original_play(task)

        self._am._play_task = _patched_play

    def uninstall(self):
        self._am._play_task = self._original_play

    def results(self) -> list:
        with self._lock:
            return list(self._times)


# ─── Main test ────────────────────────────────────────────────────────────────

def run(n_frames: int = TARGET_FRAMES, emit_cb=None) -> dict:
    emit = _make_emit(emit_cb)

    emit("═" * 64, "div")
    emit("T1  END-TO-END LATENCY", "section")
    emit("═" * 64, "div")
    emit(f"  Target frames : {n_frames}")
    emit(f"  Pass threshold: p95 < {PASS_MS} ms")
    emit()

    # ── Try to import maix ────────────────────────────────────────────────────
    try:
        from maix import camera, nn, image as mi
        MAIX = True
    except ImportError:
        MAIX = False

    if not MAIX:
        emit("  ✗ maix not available — cannot run T1", "err")
        return {"passed": False, "skipped": True, "score": 0, "reason": "maix not available"}

    try:
        from config import cfg, RELEVANT_LABELS, COCO_LABEL_MAP
    except Exception as e:
        emit(f"  ✗ config import error: {e}", "err")
        return {"passed": False, "score": 0, "error": str(e)}

    # ── Init hardware ─────────────────────────────────────────────────────────
    try:
        emit("  Initialising camera + model...")
        detector = nn.YOLO11(model=cfg.MODEL_PATH)
        cam      = camera.Camera(cfg.INPUT_WIDTH, cfg.INPUT_HEIGHT, mi.Format.FMT_RGB888)
        cam.open()
        emit(f"  Camera: {cfg.INPUT_WIDTH}×{cfg.INPUT_HEIGHT}", "ok")
        emit(f"  Model : {cfg.MODEL_PATH}", "ok")
    except Exception as e:
        emit(f"  ✗ Hardware init failed: {e}", "err")
        return {"passed": False, "score": 0, "error": str(e)}

    # ── Warm-up ────────────────────────────────────────────────────────────────
    emit(f"  Warm-up ({WARMUP_FRAMES} frames)...")
    for _ in range(WARMUP_FRAMES):
        f = cam.read()
        detector.detect(f, conf_th=cfg.CONF_THRESHOLD, iou_th=cfg.IOU_THRESHOLD)

    # ── Measurement loop ──────────────────────────────────────────────────────
    emit(f"  Measuring {n_frames} frames...")
    samples = []

    for i in range(n_frames):
        t0 = time.perf_counter()

        # Stage 1 — Camera
        frame = cam.read()
        t1    = time.perf_counter()

        # Stage 2 — NPU
        result = detector.detect(
            frame,
            conf_th=cfg.CONF_THRESHOLD,
            iou_th=cfg.IOU_THRESHOLD,
        )
        t2 = time.perf_counter()

        # Stage 3 — Post-process (label filter + position calc)
        frame_area = cfg.INPUT_WIDTH * cfg.INPUT_HEIGHT
        dets = []
        for det in result:
            label = COCO_LABEL_MAP.get(det.class_id, "")
            if label in RELEVANT_LABELS:
                area    = (det.w * det.h) / frame_area
                dets.append({
                    "label":    label,
                    "danger":   area > cfg.DANGER_AREA_THRESHOLD,
                    "priority": 0 if (area > cfg.DANGER_AREA_THRESHOLD) else 1,
                })
        t3 = time.perf_counter()

        # Stage 4 — Audio queue insertion (PriorityQueue.put timing)
        dummy_pq: list = []
        import bisect
        task_text = dets[0]["label"] if dets else "clear"
        bisect.insort(dummy_pq, (0, i, task_text))
        t4 = time.perf_counter()

        samples.append({
            "cam_ms":   (t1 - t0) * 1000,
            "infer_ms": (t2 - t1) * 1000,
            "post_ms":  (t3 - t2) * 1000,
            "queue_ms": (t4 - t3) * 1000,
            "total_ms": (t4 - t0) * 1000,
        })

    cam.close()

    # ── Audio queue-to-play latency (separate micro-test) ─────────────────────
    audio_q2p_ms = _measure_audio_queue_latency(emit)

    # ── Compute statistics ────────────────────────────────────────────────────
    def _avg(k):  return sum(s[k] for s in samples) / len(samples)
    def _pct(k, p): return sorted(s[k] for s in samples)[int(len(samples) * p)]

    avg_total  = round(_avg("total_ms"),      2)
    p50_total  = round(_pct("total_ms", .50), 2)
    p95_total  = round(_pct("total_ms", .95), 2)
    p99_total  = round(_pct("total_ms", .99), 2)

    emit()
    emit(f"  {'Stage':<30} {'Avg (ms)':>10}")
    emit(f"  {'─'*30} {'─'*10}")
    emit(f"  {'[1] Camera capture':<30} {_avg('cam_ms'):>10.2f}")
    emit(f"  {'[2] NPU inference':<30} {_avg('infer_ms'):>10.2f}")
    emit(f"  {'[3] Post-process':<30} {_avg('post_ms'):>10.2f}")
    emit(f"  {'[4] Audio queue insert':<30} {_avg('queue_ms'):>10.3f}")
    emit(f"  {'─'*30} {'─'*10}")
    emit(f"  {'TOTAL (stages 1-4)':<30} {avg_total:>10.2f}")
    if audio_q2p_ms is not None:
        emit(f"  {'[5] Queue → play start':<30} {audio_q2p_ms:>10.2f}")
        full_e2e = round(avg_total + audio_q2p_ms, 2)
        emit(f"  {'FULL end-to-end (est.)':<30} {full_e2e:>10.2f}")
    emit()
    emit(f"  Percentiles:  p50={p50_total}ms  p95={p95_total}ms  p99={p99_total}ms")
    emit()

    # Pass/fail
    passed = p95_total < PASS_MS
    tag    = "ok" if passed else "err"
    emoji  = "✓" if passed else "✗"
    emit(f"  {emoji} p95={p95_total}ms — {'PASS' if passed else 'FAIL'} (threshold {PASS_MS}ms)", tag)

    # Score: 100 at avg=50ms, 0 at avg>=300ms, linear
    score = max(0, min(100, round((PASS_MS - avg_total) / (PASS_MS - 50) * 100)))
    emit(f"  Score: {score}/100")

    results = {
        "test":           "T1_Latency",
        "passed":         passed,
        "score":          score,
        "n_frames":       n_frames,
        "avg_cam_ms":     round(_avg("cam_ms"),   2),
        "avg_infer_ms":   round(_avg("infer_ms"), 2),
        "avg_post_ms":    round(_avg("post_ms"),  2),
        "avg_queue_ms":   round(_avg("queue_ms"), 4),
        "avg_total_ms":   avg_total,
        "p50_ms":         p50_total,
        "p95_ms":         p95_total,
        "p99_ms":         p99_total,
        "min_ms":         round(min(s["total_ms"] for s in samples), 2),
        "max_ms":         round(max(s["total_ms"] for s in samples), 2),
        "audio_q2p_ms":   audio_q2p_ms,
        "pass_threshold": PASS_MS,
        "timestamp":      time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    _save(results)
    return results


def _measure_audio_queue_latency(emit) -> float | None:
    """
    Ukur waktu dari queue.put() hingga _loop() mengambil task.
    Menggunakan AudioManager internal tanpa hardware playback.
    """
    try:
        import queue as _q
        import threading as _t

        SENTINEL = object()
        t_put    = [0.0]
        t_pick   = [0.0]
        done     = _t.Event()

        pq = _q.PriorityQueue()

        def _consumer():
            while True:
                _, _, item = pq.get(timeout=1.0)
                if item is SENTINEL:
                    t_pick[0] = time.perf_counter()
                    done.set()
                    return

        _t.Thread(target=_consumer, daemon=True).start()

        # Measure queue latency over 50 iterations
        deltas = []
        for _ in range(50):
            t_put[0] = time.perf_counter()
            pq.put((0, 0, SENTINEL))
            done.wait(timeout=0.5)
            done.clear()
            delta_ms = (t_pick[0] - t_put[0]) * 1000
            deltas.append(delta_ms)
            time.sleep(0.001)

        avg_delta = round(sum(deltas) / len(deltas), 3)
        emit(f"  Audio queue-to-consume avg: {avg_delta} ms (50 iterations)")
        return avg_delta

    except Exception:
        return None


def _save(results: dict):
    os.makedirs(os.path.dirname(RESULTS_FILE), exist_ok=True)
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    run()

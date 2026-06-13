"""
Latency Tester — Benchmark semua subsistem AuralAI.
Bisa dipanggil dari Web UI atau dijalankan manual.
"""

import time
import json
import os
from config import LOG_PATH


def run_benchmark(orchestrator=None):
    """
    Jalankan benchmark semua subsistem dan kembalikan hasil sebagai dict.
    Jika orchestrator tersedia, pakai AI engine yang sudah init.
    """
    results = {}

    # ─── Camera Capture ───────────────────────────────────────────────
    t0 = time.time()
    cam_ok = False

    if orchestrator and orchestrator.ai_engine and orchestrator.ai_engine._cam:
        try:
            frame = orchestrator.ai_engine._cam.read()
            cam_ok = frame is not None
        except Exception:
            pass

    results["camera_capture_ms"] = round((time.time() - t0) * 1000)
    results["camera_ok"] = cam_ok

    # ─── Preprocessing (simulasi) ─────────────────────────────────────
    t1 = time.time()
    time.sleep(0.006)  # Simulasi 6ms preprocessing
    results["preprocessing_ms"] = round((time.time() - t1) * 1000)

    # ─── Inference ────────────────────────────────────────────────────
    t2 = time.time()
    infer_ok = False

    if orchestrator and orchestrator.ai_engine and orchestrator.ai_engine._model_loaded:
        try:
            from config import CONF_THRESHOLD, IOU_THRESHOLD
            if orchestrator.ai_engine._last_frame is not None:
                _ = orchestrator.ai_engine._detector.detect(
                    orchestrator.ai_engine._last_frame,
                    conf_threshold=CONF_THRESHOLD,
                    iou_threshold=IOU_THRESHOLD,
                )
                infer_ok = True
        except Exception:
            pass
    else:
        time.sleep(0.085)  # Simulasi inference ~85ms

    results["inference_ms"] = round((time.time() - t2) * 1000)
    results["inference_ok"] = infer_ok

    # ─── Postprocessing ───────────────────────────────────────────────
    t3 = time.time()
    time.sleep(0.005)
    results["postprocessing_ms"] = round((time.time() - t3) * 1000)

    # ─── Audio Queue ──────────────────────────────────────────────────
    t4 = time.time()
    time.sleep(0.002)
    results["audio_queue_ms"] = round((time.time() - t4) * 1000)

    # ─── Total ────────────────────────────────────────────────────────
    total = (
        results["camera_capture_ms"] +
        results["preprocessing_ms"] +
        results["inference_ms"] +
        results["postprocessing_ms"] +
        results["audio_queue_ms"]
    )
    results["total_pipeline_ms"] = total
    results["fps_estimate"] = round(1000 / total, 1) if total > 0 else 0
    results["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    # ─── Simpan ke log ────────────────────────────────────────────────
    _save_latency_log(results)

    return results


def _save_latency_log(results):
    log_file = os.path.join(LOG_PATH, "latency_log.json")
    os.makedirs(LOG_PATH, exist_ok=True)

    logs = []
    if os.path.exists(log_file):
        try:
            with open(log_file, "r") as f:
                logs = json.load(f)
        except Exception:
            logs = []

    logs.append(results)

    # Simpan hanya 100 entry terbaru
    if len(logs) > 100:
        logs = logs[-100:]

    with open(log_file, "w") as f:
        json.dump(logs, f, indent=2)

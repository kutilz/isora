"""
Context Mode — Online mode dengan OpenAI API.
Mode ini standby dan hanya aktif saat ada command dari Web UI:
  - 'describe' → scene description
  - 'qris'     → QRIS verifier
"""

import time


def run_context_tick(orch):
    """
    Context mode idle loop — hanya update snapshot dan latency kamera.
    Inference offline tidak dijalankan untuk hemat resource saat online mode.
    """
    if orch.ai_engine is None:
        time.sleep(0.1)
        return

    # Tetap capture snapshot untuk Web UI, tapi skip inference
    _, _, latency = orch.ai_engine.capture_and_infer()

    # Di context mode, clear detections (tidak pakai YOLO)
    orch.detections = []
    orch.latency = latency

    # Sedikit sleep agar tidak burn CPU
    time.sleep(0.2)

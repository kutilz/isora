"""
Context Mode — Online mode dengan OpenAI API.
Mode ini standby dan hanya aktif saat ada command dari Web UI / tombol ACTION:
  - 'describe' → scene description
  - 'qris'     → QRIS verifier

Kamera tetap terbuka tapi TIDAK dibaca tiap tick. Membaca frame tiap 0,2 detik
(padahal tanpa inferensi) membuat load CPU naik ke 5–6 di board ini sampai driver
WiFi ikut kelaparan: DNS gagal, describe ke cloud timeout, SSH putus. Frame hanya
diambil saat:
  - tombol capture ditekan — Orchestrator._handle_command mengambil frame baru
    sebelum describe (AIEngine.grab_fresh_frame),
  - web sedang menampilkan kamera (orch.wants_preview()), atau
  - device belum di-pair dan menunggu QR pairing di depan kamera.
"""

import time


def _needs_frames(orch) -> bool:
    """Whether anyone is consuming frames between button presses."""
    if orch.wants_preview():
        return True
    cloud = getattr(orch, "cloud", None)
    return cloud is not None and cloud.wants_qr_scan()


def run_context_tick(orch):
    """
    Context mode idle loop — baca kamera hanya kalau ada yang menonton preview
    atau menunggu QR pairing. Inference offline tidak dijalankan.
    """
    if orch.ai_engine is None:
        time.sleep(0.1)
        return

    # Di context mode, clear detections (tidak pakai YOLO)
    orch.detections = []

    if not _needs_frames(orch):
        # Park on the mode event rather than sleeping: a describe queued from
        # the button or the web is picked up at the top of the next loop pass.
        orch._mode_event.wait(timeout=0.2)
        return

    # Tetap capture snapshot untuk Web UI, tapi skip inference
    _, _, latency = orch.ai_engine.capture_and_infer()
    orch.latency = latency

    # Sedikit sleep agar tidak burn CPU
    time.sleep(0.2)

"""
Explorer Mode — Offline YOLO object detection tick.
Called once per AI loop iteration when mode == "explorer".
"""

import time


def run_explorer_tick(orch):
    """
    One Explorer Mode cycle:
      1. Capture + inference
      2. Update shared detections + latency
      3. Queue audio for the top-priority objects
    """
    if orch.ai_engine is None:
        time.sleep(0.1)
        return

    _, detections, latency = orch.ai_engine.capture_and_infer()

    orch.detections = detections
    orch.latency    = latency

    if not detections or orch.audio_manager is None:
        return

    # Sort: dangerous first, then by confidence descending
    sorted_dets = sorted(
        detections,
        key=lambda d: (d.get("is_danger", False), d.get("confidence", 0)),
        reverse=True,
    )

    for det in sorted_dets[:2]:
        orch.audio_manager.queue_object(
            label=det["label"],
            position=det["position"],
            is_danger=det.get("is_danger", False),
        )

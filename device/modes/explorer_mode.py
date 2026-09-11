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

    # Just after a user interaction, stay quiet so the action's audio (mode
    # confirmation / description / repeat) is heard instead of being drowned by
    # detection alerts. Detections were still updated above for the dashboard.
    if orch.detection_audio_suppressed():
        return

    # Single nav-speech gate (Decision 1A/E1A): the AnnouncePolicy ranks
    # danger/near first, speaks on change, re-announces an approaching hazard on
    # a timer, and stays quiet on an unchanged calm scene — replacing the old
    # "top-2 every tick + back-off" loop. Ranking and the per-tick cap live
    # inside the policy.
    orch.audio_manager.announce_detections(detections)

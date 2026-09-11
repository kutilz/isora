"""Idle Mode — the neutral resting state.

The device is powered, reachable over the network and listening for a button
press, but it captures nothing, infers nothing and says nothing. This is where
it boots (see cfg["boot_mode"]) and where the mode cycle comes home to.

Nothing here is a stub: the cheapest tick is the point. A mode that still
pulled frames would keep the camera pipeline (and one whole RISC-V core) warm
for output nobody asked for.
"""

# How long an idle tick parks before looking again. Long, because nothing in
# this mode is time-sensitive — a mode change wakes the wait immediately.
IDLE_TICK_S = 0.5


def run_idle_tick(orch):
    """One idle cycle: forget stale state, then wait for something to change."""
    orch.detections = []
    orch.latency = {
        "camera_ms": 0, "inference_ms": 0,
        "postproc_ms": 0, "total_ms": 0, "fps": 0,
    }
    # Park on the mode event rather than sleeping, so a button press is acted
    # on the instant it lands instead of up to IDLE_TICK_S later.
    orch._mode_event.wait(timeout=IDLE_TICK_S)

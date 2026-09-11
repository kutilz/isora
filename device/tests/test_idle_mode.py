"""Idle mode: the device is on, reachable, and doing nothing.

This is the state the device boots into and the one a user returns to when
they are done. "Doing nothing" has to be literal — a mode that still reads
frames or still speaks is just explorer with the volume down, and it would
keep the SoC (and the user) busy for no reason.
"""

import threading

from modes.idle_mode import run_idle_tick


class _SpyEngine:
    def __init__(self):
        self.captures = 0

    def capture_and_infer(self):
        self.captures += 1
        return None, [], {}


class _SpyAudio:
    def __init__(self):
        self.spoken = []

    def __getattr__(self, name):
        def _record(*a, **k):
            self.spoken.append((name, a, k))
        return _record


class _FakeOrch:
    def __init__(self):
        self.ai_engine     = _SpyEngine()
        self.audio_manager = _SpyAudio()
        self.detections    = ["stale"]
        self.latency       = {"fps": 30}
        self._mode_event   = threading.Event()


def test_idle_never_reads_a_frame_or_speaks():
    orch = _FakeOrch()
    orch._mode_event.set()          # don't spend the tick's park time here
    for _ in range(3):
        run_idle_tick(orch)
    assert orch.ai_engine.captures == 0
    assert orch.audio_manager.spoken == []


def test_idle_clears_stale_detections_so_the_dashboard_stops_lying():
    orch = _FakeOrch()
    orch._mode_event.set()
    run_idle_tick(orch)
    assert orch.detections == []
    assert orch.latency["fps"] == 0


def test_idle_wakes_immediately_on_a_mode_change():
    # The tick parks on the mode event, so a button press is acted on at once
    # instead of after a fixed sleep.
    orch = _FakeOrch()
    orch._mode_event.set()
    started = threading.Event()

    def _run():
        started.set()
        run_idle_tick(orch)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    started.wait(1.0)
    t.join(timeout=0.5)
    assert not t.is_alive()


# ─── Who is allowed to hold the camera ────────────────────────────────────────

from core.orchestrator import Orchestrator   # noqa: E402


def test_idle_mode_does_not_hold_the_camera():
    # Measured on the device: with the camera merely OPEN and never read, the
    # app still burned ~25-30% of the single core and the kernel's
    # [vi_event_handle] stayed busy — the sensor streams into the VI buffers
    # whether or not anyone reads them. An idle mode that keeps the camera is
    # not idle, it is just quiet.
    assert Orchestrator.engine_wanted("idle", collecting=False) is False


def test_the_working_modes_do_hold_the_camera():
    for mode in ("explorer", "context", "qris"):
        assert Orchestrator.engine_wanted(mode, collecting=False) is True


def test_dataset_capture_always_wins_the_camera():
    # Exactly one of AIEngine / DataCollector may hold it; the collector's
    # claim outranks every mode.
    for mode in ("idle", "explorer", "context", "qris"):
        assert Orchestrator.engine_wanted(mode, collecting=True) is False

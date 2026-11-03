"""Context mode: the camera stays open but is only read when someone needs a frame.

Reading a frame every 0.2 s with no inference to show for it drove the load on
this single-core SoC to 5-6, and the WiFi driver starved with it: DNS lookups
failed and the very describe the mode exists for timed out. So between presses
the mode reads nothing, unless the web page is showing the camera or a pairing
QR is expected in front of it.
"""

import threading

from core.orchestrator import Orchestrator
from modes.context_mode import run_context_tick


class _SpyEngine:
    def __init__(self, log=None):
        self.captures = 0
        self.log = log if log is not None else []

    def capture_and_infer(self):
        self.captures += 1
        return None, [], {"fps": 9}

    def grab_fresh_frame(self):
        self.log.append("grab")
        return True

    def trigger_scene_description(self):
        self.log.append("describe")


class _FakeCloud:
    def __init__(self, wants):
        self._wants = wants

    def wants_qr_scan(self):
        return self._wants


class _FakeOrch:
    def __init__(self, preview=False, cloud=None):
        self.ai_engine   = _SpyEngine()
        self.cloud       = cloud
        self.detections  = ["stale"]
        self.latency     = {}
        self._mode_event = threading.Event()
        self._preview    = preview

    def wants_preview(self):
        return self._preview


def test_context_reads_no_frame_between_presses():
    orch = _FakeOrch(cloud=_FakeCloud(False))
    orch._mode_event.set()          # don't spend the tick's park time here
    for _ in range(3):
        run_context_tick(orch)
    assert orch.ai_engine.captures == 0
    assert orch.detections == []


def test_context_reads_frames_while_the_web_shows_the_camera():
    orch = _FakeOrch(preview=True)
    run_context_tick(orch)
    assert orch.ai_engine.captures == 1
    assert orch.latency == {"fps": 9}


def test_context_reads_frames_while_waiting_for_a_pairing_qr():
    orch = _FakeOrch(cloud=_FakeCloud(True))
    run_context_tick(orch)
    assert orch.ai_engine.captures == 1


class _CmdOrch:
    """Just enough of an Orchestrator to run _handle_command('describe')."""

    def __init__(self, mode):
        self.mode = mode
        self.log = []
        self.ai_engine = _SpyEngine(self.log)

    def note_user_interaction(self):
        pass


def test_describe_in_context_takes_the_picture_at_the_press():
    orch = _CmdOrch("context")
    Orchestrator._handle_command(orch, {"cmd": "describe"})
    assert orch.log == ["grab", "describe"]


def test_describe_in_explorer_uses_the_frame_the_loop_already_has():
    # Explorer reads every tick, so its last frame is already current.
    orch = _CmdOrch("explorer")
    Orchestrator._handle_command(orch, {"cmd": "describe"})
    assert orch.log == ["describe"]

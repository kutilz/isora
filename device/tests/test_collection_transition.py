"""When to hand the camera to (and take it back from) dataset capture.

The rule used to be inferred from "is there an AI engine?", which held only
because collection mode was the one and only state without one. Idle mode
broke that: with no engine and no capture running, every single tick decided
the device had just left collection mode — re-running the exit path and
announcing "Mode normal aktif." over and over, forever.
"""

from core.orchestrator import Orchestrator

transition = Orchestrator.collection_transition


def test_starting_capture_hands_the_camera_over_once():
    assert transition(want_collection=True, in_collection=False) == "enter"
    # Already there: nothing more to do, and nothing more to announce.
    assert transition(want_collection=True, in_collection=True) is None


def test_stopping_capture_takes_the_camera_back_once():
    assert transition(want_collection=False, in_collection=True) == "exit"


def test_a_device_that_was_never_collecting_never_announces_leaving():
    # The regression: idle mode has no AI engine either, and this fired every
    # tick of the AI loop.
    assert transition(want_collection=False, in_collection=False) is None

"""Heat changes what the device DOES, not what it SAYS.

The old behaviour announced "suhu tinggi" and left the workload untouched:
the one person who cannot act on that warning — someone walking with the
device strapped on — was the only one who heard it. The device is the party
that can actually do something about its own temperature, so it does.
"""

from core.orchestrator import Orchestrator


class _NullLogger:
    def __getattr__(self, _name):
        return lambda *a, **k: None


class _SpyAudio:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def _record(*a, **k):
            self.calls.append((name, a, k))
        return _record


def _orch():
    orch = Orchestrator(logger=_NullLogger())
    orch.audio_manager = _SpyAudio()
    return orch


def test_getting_hot_is_never_announced():
    orch = _orch()
    for temp in (70.0, 78.0, 84.0, 91.0, 99.0):
        orch.on_health_sample({"cpu_temp_c": temp})
    assert orch.audio_manager.calls == []


def test_getting_hot_cuts_the_work_the_loop_is_allowed_to_do():
    orch = _orch()
    orch.on_health_sample({"cpu_temp_c": 45.0})
    cool = orch.power_plan
    orch.on_health_sample({"cpu_temp_c": 95.0})
    hot = orch.power_plan
    assert hot.target_fps < cool.target_fps
    assert hot.tier != cool.tier


def test_cooling_down_gives_the_work_back():
    orch = _orch()
    orch.on_health_sample({"cpu_temp_c": 95.0})
    orch.on_health_sample({"cpu_temp_c": 40.0})
    assert orch.power_plan.tier == "normal"
    assert orch.audio_manager.calls == []


def test_the_loop_rests_longer_once_the_device_is_hot():
    # This is the whole fix. The old code set camera_fps on a camera that had
    # already been opened, so "throttling" bought exactly zero idle time.
    orch = _orch()
    orch.on_health_sample({"cpu_temp_c": 45.0})
    cool_rest = orch.tick_delay(elapsed_s=0.005)
    orch.on_health_sample({"cpu_temp_c": 95.0})
    hot_rest = orch.tick_delay(elapsed_s=0.005)
    assert hot_rest > cool_rest > 0


def test_a_tick_that_already_took_too_long_is_not_delayed_further():
    orch = _orch()
    orch.on_health_sample({"cpu_temp_c": 45.0})
    assert orch.tick_delay(elapsed_s=2.0) == 0.0


# ─── Preview: the frame nobody was looking at ─────────────────────────────────

def test_no_preview_is_encoded_until_someone_actually_looks():
    # Encoding the dashboard JPEG costs ~17ms of a ~18ms tick on this SoC, and
    # the device spent all day doing it for a page nobody had open.
    orch = _orch()
    orch.on_health_sample({"cpu_temp_c": 45.0})
    assert orch.wants_preview() is False

    orch.note_preview_request()
    assert orch.wants_preview() is True


def test_the_preview_stops_again_once_the_watcher_goes_away():
    orch = _orch()
    orch.on_health_sample({"cpu_temp_c": 45.0})
    orch.note_preview_request(now=100.0)
    assert orch.wants_preview(now=101.0) is True     # still polling
    assert orch.wants_preview(now=130.0) is False    # tab closed


def test_heat_wins_over_a_watcher():
    # A pendamping watching the dashboard does not get to keep the device hot.
    orch = _orch()
    orch.note_preview_request(now=100.0)
    orch.on_health_sample({"cpu_temp_c": 95.0})
    assert orch.wants_preview(now=101.0) is False

"""Guards for the button-mash hardening.

Every test here corresponds to something a real device did, measured over two
stress runs (308 and 1040 simulated presses):

  * the app froze inside AIEngine.release() and never logged again, with the
    audio codec looping one phrase until power was pulled;
  * 24 YOLO loads against 20 releases — four NPU allocations leaked, which is
    what made the freeze probabilistic rather than immediate;
  * 41 then 147 presses silently dropped;
  * the volume the user selected never reached the speaker at all.

These are behaviour tests: they assert what the device does, not how.
"""

import json
import threading
import types

import pytest

import core.audio_manager as am_mod
from core.orchestrator import Orchestrator


class _NullLogger:
    def __getattr__(self, _name):
        return lambda *a, **k: None


# ── switch_mode must not touch the hardware ──────────────────────────────────

class _RecordingEngine:
    """Fails loudly if the model is touched from outside the AI loop."""

    def __init__(self):
        self.calls = []

    def reload_model(self):
        self.calls.append(("reload", threading.current_thread().name))

    def release_model(self):
        self.calls.append(("release", threading.current_thread().name))


@pytest.fixture
def orch(monkeypatch, tmp_path):
    import config as config_mod
    monkeypatch.setattr(config_mod, "_CONFIG_PATH", tmp_path / "config.json")
    o = Orchestrator(_NullLogger())
    o.audio_manager = None
    return o


def test_switch_mode_does_no_hardware_work(orch):
    """The freeze came from an NPU load starting on the button thread while the
    AI thread was closing the camera. switch_mode must be pure state + audio."""
    engine = _RecordingEngine()
    orch.ai_engine = engine

    orch.switch_mode("explorer")
    orch.switch_mode("context")
    orch.switch_mode("idle")

    assert engine.calls == [], (
        "switch_mode reached into the engine — that is the interleaving that "
        "wedged the device")
    assert orch.mode == "idle"


def test_engine_sync_happens_on_the_ai_loop_and_is_idempotent(orch):
    """Ten mode presses during one camera open must collapse to one load."""
    engine = _RecordingEngine()
    orch.ai_engine = engine

    for _ in range(10):
        orch._sync_engine_to_mode("explorer")
    assert [c[0] for c in engine.calls] == ["reload"] * 10, (
        "sync must be safe to call every tick")

    # reload_model itself is the no-op guard on the engine side; the point here
    # is that the orchestrator never has to remember what it already did.
    engine.calls.clear()
    orch._sync_engine_to_mode("idle")
    assert engine.calls == [("release", threading.current_thread().name)]


def test_engine_sync_survives_an_engine_that_raises(orch):
    class _Angry:
        def reload_model(self):
            raise RuntimeError("NPU busy")

        def release_model(self):
            raise RuntimeError("NPU busy")

    orch.ai_engine = _Angry()
    orch._sync_engine_to_mode("explorer")   # must not propagate
    orch._sync_engine_to_mode("idle")


# ── the watchdog must still be registered across the dangerous call ──────────

class _Watchdog:
    def __init__(self):
        self.registered = set()
        self.seen_during_release = None

    def register(self, name, **_kw):
        self.registered.add(name)

    def unregister(self, name):
        self.registered.discard(name)

    def heartbeat(self, _name):
        pass


def test_watchdog_is_dropped_only_after_release_returns(orch):
    """Unregistering first left the one call that actually hangs unsupervised."""
    wd = _Watchdog()
    wd.registered.add("ai_engine")
    orch.watchdog = wd

    class _Engine:
        def release(self):
            wd.seen_during_release = "ai_engine" in wd.registered

    orch.ai_engine = _Engine()
    orch._release_aural_engine()

    assert wd.seen_during_release is True, (
        "the watchdog entry was dropped before the blocking call")
    assert "ai_engine" not in wd.registered, "entry must be dropped afterwards"
    assert orch.ai_engine is None


def test_the_watchdog_callback_never_touches_the_camera(orch):
    """The watchdog runs on its OWN thread, and exactly one thread may enter
    the cvitek VI open/close path.

    Regression for a fix that made things worse: keeping the watchdog entry
    registered across release() (so a hang is visible) while its restart_fn was
    still AIEngine.reload — which begins with release() — let the watchdog fire
    a camera teardown from a second thread during a mode mash. The board reset.
    """
    touched = []

    class _Engine:
        def release(self):
            touched.append("release")

        def reload(self):
            touched.append("reload")

        def release_model(self):
            touched.append("release_model")

        def reload_model(self):
            touched.append("reload_model")

    orch.ai_engine = _Engine()
    orch._request_engine_restart()

    assert touched == [], "the watchdog callback reached the hardware"
    assert orch._engine_restart_requested is True

    # ...and the AI loop is what actually performs it.
    orch.watchdog = _Watchdog()
    orch._start_aural_engine = lambda: touched.append("start")
    orch._service_engine_restart_request()
    assert "release" in touched and "start" in touched
    assert orch._engine_restart_requested is False


def test_a_restart_request_is_a_no_op_without_an_engine(orch):
    orch.ai_engine = None
    orch._request_engine_restart()
    started = []
    orch._start_aural_engine = lambda: started.append(1)
    orch._service_engine_restart_request()
    assert started == []


def test_release_clears_the_engine_even_when_release_raises(orch):
    class _Engine:
        def release(self):
            raise RuntimeError("VI close failed")

    orch.watchdog = _Watchdog()
    orch.ai_engine = _Engine()
    orch._release_aural_engine()
    assert orch.ai_engine is None


# ── loop liveness is independent of the engine ───────────────────────────────

def test_loop_health_is_reported_without_an_engine(orch):
    """idle is the default boot mode and holds no engine; a loop that died
    there used to look exactly like a healthy one."""
    orch.ai_engine = None
    assert orch.loop_healthy(stale_after_s=60.0) is True

    orch._loop_beat -= 120.0
    assert orch.loop_healthy(stale_after_s=60.0) is False


# ── volume actually reaches the speaker ──────────────────────────────────────

def test_volume_floor_is_quieter_than_the_ceiling_and_not_silent():
    import audioop
    raw = bytes([0x00, 0x40] * 200)

    full  = am_mod.apply_software_gain(raw, 100)
    half  = am_mod.apply_software_gain(raw, 50)
    floor = am_mod.apply_software_gain(raw, 20)

    assert audioop.max(full, 2) > audioop.max(half, 2) > audioop.max(floor, 2)
    assert audioop.max(floor, 2) > 0, "the button floor must stay audible"
    assert len(floor) == len(raw)


def test_gain_is_a_no_op_on_bad_input():
    assert am_mod.apply_software_gain(b"", 50) == b""
    assert am_mod.apply_software_gain(b"ab", None) == b"ab"
    assert am_mod.apply_software_gain(b"ab", "loud") == b"ab"


# ── volume mode does not trap the user ───────────────────────────────────────

def _open_volume_mode(orch):
    orch._enter_volume_mode()
    assert orch._in_volume_mode()


def test_a_no_op_press_at_the_floor_does_not_hold_the_mode_open(orch, monkeypatch):
    from config import cfg
    cfg.set("audio_volume", cfg.get("volume_button_min", 20))
    _open_volume_mode(orch)

    with orch._btn_lock:
        deadline_before = orch._volume_until
    orch._volume_step(-1)                       # already at the floor: no-op
    with orch._btn_lock:
        deadline_after = orch._volume_until

    assert deadline_after == deadline_before, (
        "a press that changed nothing re-armed the modal timeout — the user "
        "could never press their way back to the mode button")


def test_a_real_step_does_hold_the_mode_open(orch):
    from config import cfg
    cfg.set("audio_volume", 60)
    _open_volume_mode(orch)
    with orch._btn_lock:
        before = orch._volume_until
    orch._volume_step(-1)
    with orch._btn_lock:
        after = orch._volume_until
    assert after >= before


# ── a queued press keeps the meaning it had when it was pressed ──────────────

def test_a_queued_press_is_routed_against_the_state_at_press_time(orch, monkeypatch):
    seen = {}
    monkeypatch.setattr(orch, "_volume_step", lambda d: seen.setdefault("volume", d))
    monkeypatch.setattr(orch, "_press_cue", lambda: None)
    monkeypatch.setattr(orch, "switch_mode", lambda m: seen.setdefault("mode", m))

    # Pressed while volume mode was open, handled after it timed out.
    assert not orch._in_volume_mode()
    orch._on_button(False, in_volume=True)

    assert seen.get("volume") == -1, "queued press was re-read against a stale mode"
    assert "mode" not in seen


def test_a_live_press_still_uses_the_current_state(orch, monkeypatch):
    seen = {}
    monkeypatch.setattr(orch, "_press_cue", lambda: None)
    monkeypatch.setattr(orch, "switch_mode", lambda m: seen.setdefault("mode", m))
    orch._on_button(False)                      # in_volume defaults to None
    assert "mode" in seen


# ── config survives two writers ──────────────────────────────────────────────

def test_concurrent_saves_never_publish_a_partial_document(tmp_path, monkeypatch):
    """One shared tmp path meant one writer could replace a file the other was
    still streaming into — taking device_token and every API key with it."""
    import config as config_mod
    path = tmp_path / "config.json"
    monkeypatch.setattr(config_mod, "_CONFIG_PATH", path)
    c = config_mod.Config()
    c.set("device_token", "keep-me")

    errors = []

    def _hammer(n):
        try:
            for i in range(30):
                c.set("probe_%d" % n, i)
                c.save()
        except Exception as e:      # pragma: no cover - failure detail
            errors.append(e)

    threads = [threading.Thread(target=_hammer, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors
    data = json.loads(path.read_text())          # must parse: never truncated
    assert data["device_token"] == "keep-me"
    leftovers = list(tmp_path.glob("*.tmp*"))
    assert leftovers == [], "temp files leaked: %s" % leftovers


def test_save_async_coalesces_and_still_lands(tmp_path, monkeypatch):
    import config as config_mod
    path = tmp_path / "config.json"
    monkeypatch.setattr(config_mod, "_CONFIG_PATH", path)
    c = config_mod.Config()

    for i in range(20):
        c.set("audio_volume", 20 + i)
        c.save_async(delay_s=0.05)

    deadline = threading.Event()
    deadline.wait(0.6)
    assert json.loads(path.read_text())["audio_volume"] == 39


# ── hazards are never silenced by the interaction mute ───────────────────────

def test_hazards_survive_the_post_interaction_mute():
    from utils.announce_policy import is_danger
    assert is_danger({"is_danger": True, "tier": "far"}) is True
    assert is_danger({"tier": "near"}) is True
    assert is_danger({"tier": "far"}) is False


def test_explorer_speaks_hazards_while_muted(monkeypatch):
    import modes.explorer_mode as ex

    spoken = []

    engine = types.SimpleNamespace(
        capture_and_infer=lambda: (
            None,
            [{"label": "mobil", "tier": "near", "is_danger": True},
             {"label": "kursi", "tier": "far"}],
            {},
        )
    )
    orch = types.SimpleNamespace(
        ai_engine=engine,
        detections=[],
        latency={},
        audio_manager=types.SimpleNamespace(
            announce_detections=lambda d: spoken.extend(d)),
        detection_audio_suppressed=lambda: True,
    )

    ex.run_explorer_tick(orch)

    labels = [d["label"] for d in spoken]
    assert labels == ["mobil"], (
        "the mute dropped a hazard, or failed to drop the non-hazard")


def test_explorer_stays_silent_when_only_calm_objects_are_muted():
    import modes.explorer_mode as ex

    spoken = []
    engine = types.SimpleNamespace(
        capture_and_infer=lambda: (None, [{"label": "kursi", "tier": "far"}], {})
    )
    orch = types.SimpleNamespace(
        ai_engine=engine,
        detections=[],
        latency={},
        audio_manager=types.SimpleNamespace(
            announce_detections=lambda d: spoken.extend(d)),
        detection_audio_suppressed=lambda: True,
    )
    ex.run_explorer_tick(orch)
    assert spoken == []

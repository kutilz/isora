"""Volume mode: the chord that opens it, and the floor that keeps it usable.

Volume is the one setting a blind user can verify without help — they hear the
result — but it is also the one setting that can take that ability away. So the
properties pinned here are less about arithmetic than about what the device must
never do: never fall silent from the buttons, never leave the mode open, never
let the chord that opened it also cycle the mode on the way out.
"""

import json
import threading
import time

import pytest

import config as config_mod
from config import cfg
from core.orchestrator import Orchestrator


class _Audio:
    """Records what the user would have heard, in order."""

    def __init__(self):
        self.cues = []

    def user_barge_in(self, cue_wav="chime_press.wav"):
        self.cues.append(cue_wav)

    def queue_cue(self, wav_name, priority=None, label=None):
        self.cues.append(wav_name)

    def queue_system(self, event):
        self.cues.append(f"sys:{event}")

    def queue_info(self, text):
        self.cues.append("info")

    def stop(self):
        pass


class _Logger:
    def info(self, *a, **k):      pass
    def warn(self, *a, **k):      pass
    def debug(self, *a, **k):     pass
    def exception(self, *a, **k): pass


@pytest.fixture
def cfgset():
    """Set config keys for one test and put the singleton back afterwards."""
    saved = {}

    def _set(key, value):
        saved.setdefault(key, cfg.get(key))
        cfg.set(key, value)

    yield _set
    for key, value in saved.items():
        cfg.set(key, value)


@pytest.fixture
def orch(tmp_path, monkeypatch, cfgset):
    # cfg.save() must land in tmp, not on the real /root/config.json.
    monkeypatch.setattr(config_mod, "_CONFIG_PATH", tmp_path / "config.json")
    # No GPIO in a test process: unset both pads so __init__ starts no listener
    # threads, and drive the chord state directly instead.
    cfgset("button_pin_mode", "")
    cfgset("button_pin_action", "")
    cfgset("audio_volume", 80)
    cfgset("volume_step", 10)
    cfgset("volume_button_min", 20)
    cfgset("volume_button_max", 100)
    cfgset("button_chord_hold_s", 0.6)
    cfgset("volume_mode_timeout_s", 30.0)   # long: the timer must not interfere

    o = Orchestrator(_Logger())
    o.audio_manager = _Audio()
    yield o
    o._running = False                      # retire the SimBtn worker


def _hold_both(orch, seconds_ago=1.0):
    """Both buttons down, held together for `seconds_ago` seconds."""
    t = time.monotonic() - seconds_ago
    orch._note_button_down("mode", t)
    orch._note_button_down("action", t)


# ─── The step policy ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("cur,direction,want", [
    (80,  +1, 90),
    (80,  -1, 70),
    (95,  +1, 100),   # a partial step still reaches the ceiling
    (100, +1, 100),   # at the ceiling: unchanged -> caller plays the limit cue
    (25,  -1, 20),    # a partial step still reaches the floor
    (20,  -1, 20),    # at the floor: unchanged
    (30,  -1, 20),
])
def test_step_volume_moves_one_step_and_stops_at_the_limits(cur, direction, want):
    assert Orchestrator.step_volume(cur, direction) == want


def test_below_the_floor_down_does_nothing_but_up_climbs_out():
    """audio_volume can be set under the floor from the web UI or a cloud push.

    Down must not answer "quieter" with a jump UP to the floor — that is the
    opposite of what was asked. Up from there lands on the floor, so the buttons
    are never a dead end.
    """
    assert Orchestrator.step_volume(5, -1) == 5
    assert Orchestrator.step_volume(5, +1) == 20


def test_step_volume_survives_junk_config():
    """Every input here comes from a JSON file a cloud push can write."""
    assert Orchestrator.step_volume("eighty", +1) == 90
    assert Orchestrator.step_volume(80, +1, step="ten") == 90
    assert Orchestrator.step_volume(80, +1, lo="x", hi=None) == 90
    # Swapped bounds must not invert into "louder is quieter".
    assert Orchestrator.step_volume(50, -1, lo=100, hi=20) == 40


# ─── The chord ───────────────────────────────────────────────────────────────

def test_one_button_held_alone_is_never_a_chord(orch):
    orch._note_button_down("mode", time.monotonic() - 5.0)
    orch._poll_chord()
    assert not orch._in_volume_mode()


def test_both_held_briefly_is_not_a_chord_yet(orch):
    _hold_both(orch, seconds_ago=0.1)
    orch._poll_chord()
    assert not orch._in_volume_mode()


def test_chord_measures_from_the_later_press(orch):
    """Nobody presses two buttons on the same millisecond. The hold is "together
    for 0.6s", not "one of them has been down 0.6s"."""
    now = time.monotonic()
    orch._note_button_down("mode", now - 5.0)     # held a long time
    orch._note_button_down("action", now - 0.1)   # only just joined
    orch._poll_chord()
    assert not orch._in_volume_mode()


def test_chord_opens_volume_mode_and_says_so(orch):
    _hold_both(orch)
    orch._poll_chord()
    assert orch._in_volume_mode()
    # Chime AND spoken label: a modal state has to announce that it is modal.
    assert orch.audio_manager.cues == ["chime_vol_enter.wav", "sys:atur_volume"]


def test_chord_fires_once_however_often_both_threads_poll(orch):
    """Both listener threads poll ~50x/s while held. A second fire would toggle
    the mode straight back off under the user's fingers."""
    _hold_both(orch)
    for _ in range(20):
        orch._poll_chord()
    assert orch._in_volume_mode()
    assert orch.audio_manager.cues.count("chime_vol_enter.wav") == 1


def test_the_hold_that_opened_the_mode_never_also_fires_its_buttons(orch):
    """Releasing the chord must not cycle the mode / fire a describe."""
    _hold_both(orch)
    orch._poll_chord()
    assert orch._note_button_up("mode") is True
    assert orch._note_button_up("action") is True


def test_a_release_with_no_chord_is_left_alone(orch):
    orch._note_button_down("mode", time.monotonic())
    assert orch._note_button_up("mode") is False


def test_chording_again_closes_the_mode(orch):
    _hold_both(orch)
    orch._poll_chord()
    orch._note_button_up("mode")
    orch._note_button_up("action")

    _hold_both(orch)
    orch._poll_chord()
    assert not orch._in_volume_mode()
    assert orch.audio_manager.cues[-1] == "chime_vol_exit.wav"


def test_a_dead_listener_thread_cannot_leave_a_button_stuck_down(orch):
    """The listener calls _note_button_up() from its exception path. Without it
    the other button, held alone, would satisfy the chord test forever."""
    orch._note_button_down("mode", time.monotonic() - 5.0)
    orch._note_button_up("mode")                    # thread died, cleaned up
    orch._note_button_down("action", time.monotonic() - 5.0)
    orch._poll_chord()
    assert not orch._in_volume_mode()


# ─── Stepping inside the mode ────────────────────────────────────────────────

def test_mode_steps_down_and_action_steps_up(orch, monkeypatch):
    switched = []
    commands = []
    monkeypatch.setattr(orch, "switch_mode", lambda m: switched.append(m))
    monkeypatch.setattr(orch, "set_pending_command",
                        lambda c, d=None: commands.append(c))
    _hold_both(orch)
    orch._poll_chord()
    orch.audio_manager.cues.clear()

    orch._on_button(False)
    assert cfg.get("audio_volume") == 70
    orch._on_action_button(False)
    assert cfg.get("audio_volume") == 80

    assert orch.audio_manager.cues == ["chime_vol_down.wav", "chime_vol_up.wav"]
    # The presses belong to volume mode alone — no mode cycle, no describe.
    assert switched == [] and commands == []


def test_the_buttons_can_never_mute_the_device(orch):
    """The safety property. Audio is the only channel the user has; a device
    they silenced from the buttons cannot tell them how to get it back."""
    _hold_both(orch)
    orch._poll_chord()
    for _ in range(20):
        orch._on_button(False)
    assert cfg.get("audio_volume") == cfg.get("volume_button_min")


def test_a_press_at_the_limit_says_nothing_moved(orch):
    cfg.set("audio_volume", 100)
    _hold_both(orch)
    orch._poll_chord()
    orch.audio_manager.cues.clear()

    orch._on_action_button(False)
    assert cfg.get("audio_volume") == 100
    # Not the error bell: nothing failed, the level simply cannot go higher.
    assert orch.audio_manager.cues == ["chime_vol_limit.wav"]


def test_each_step_keeps_the_mode_open(orch):
    _hold_both(orch)
    orch._poll_chord()
    with orch._btn_lock:
        orch._volume_until = time.monotonic() + 0.05   # about to expire
    orch._on_button(False)
    assert orch._in_volume_mode()


def test_outside_volume_mode_the_buttons_are_unchanged(orch, monkeypatch):
    switched = []
    monkeypatch.setattr(orch, "switch_mode", lambda m: switched.append(m))
    cfg.set("audio_volume", 80)

    orch._on_button(False)

    assert switched == [orch.next_mode(orch.mode)]
    assert cfg.get("audio_volume") == 80


# ─── Closing the mode ────────────────────────────────────────────────────────

def test_the_level_is_written_to_disk_when_the_mode_closes(tmp_path, orch):
    """Steps live in memory (so each one is audible immediately); the flash
    write happens once, on the way out, instead of on every tap."""
    _hold_both(orch)
    orch._poll_chord()
    orch._on_button(False)
    orch._exit_volume_mode()

    saved = json.loads((tmp_path / "config.json").read_text())
    assert saved["audio_volume"] == 70


def test_exit_is_idempotent(orch):
    _hold_both(orch)
    orch._poll_chord()
    orch._exit_volume_mode()
    orch.audio_manager.cues.clear()
    orch._exit_volume_mode()
    assert orch.audio_manager.cues == []


def test_shutdown_keeps_a_level_set_moments_earlier(tmp_path, orch, monkeypatch):
    monkeypatch.setattr(orch, "switch_mode", lambda m: None)
    _hold_both(orch)
    orch._poll_chord()
    orch._on_action_button(False)          # 80 -> 90, not yet on disk

    orch._ai_loop_stopped.set()            # nothing to wait for in this process
    orch.stop()

    saved = json.loads((tmp_path / "config.json").read_text())
    assert saved["audio_volume"] == 90


def test_the_mode_closes_itself_when_the_user_walks_away(orch, cfgset):
    """Left open, the next accidental press would move the volume instead of
    describing the scene."""
    cfgset("volume_mode_timeout_s", 1.0)
    _hold_both(orch)
    orch._poll_chord()
    assert orch._in_volume_mode()

    # Wait for the CUE, not just the deadline: the mode stops accepting steps
    # the moment it expires, and the timer thread announces it a beat later.
    deadline = time.monotonic() + 3.0
    while ("chime_vol_exit.wav" not in orch.audio_manager.cues
           and time.monotonic() < deadline):
        time.sleep(0.05)
    assert not orch._in_volume_mode()
    assert orch.audio_manager.cues[-1] == "chime_vol_exit.wav"


def test_a_stale_timer_cannot_close_a_newer_session(orch):
    """Enter, leave, enter again: the first session's timer thread must not
    slam the door on the second."""
    _hold_both(orch)
    orch._poll_chord()
    stale_gen = orch._volume_gen
    orch._exit_volume_mode()
    orch._note_button_up("mode")
    orch._note_button_up("action")

    _hold_both(orch)
    orch._poll_chord()
    orch._exit_volume_mode(gen=stale_gen)
    assert orch._in_volume_mode()


# ─── The web fallback ────────────────────────────────────────────────────────

def test_the_page_can_reach_the_chord_on_a_unit_with_dead_buttons(orch):
    assert orch.simulate_button("chord") is True
    assert orch.simulate_button("nonsense") is False

    deadline = time.monotonic() + 2.0
    while not orch._in_volume_mode() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert orch._in_volume_mode()


def test_the_chord_state_is_shared_safely_between_the_two_listeners(orch):
    """The real callers are two GPIO threads polling in lockstep."""
    barrier = threading.Barrier(2)

    def press(role):
        t = time.monotonic() - 1.0
        orch._note_button_down(role, t)
        barrier.wait()
        for _ in range(50):
            orch._poll_chord()

    threads = [threading.Thread(target=press, args=(r,))
               for r in ("mode", "action")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert orch._in_volume_mode()
    assert orch.audio_manager.cues.count("chime_vol_enter.wav") == 1

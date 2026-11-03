"""Online navigation: explorer + ACTION, a cloud sentence every few seconds.

What is pinned here is what the narrator must never do to someone walking with
it: talk over itself, stack cloud calls on a 128 MB board, speak an answer about
a place they passed metres ago, keep talking after they switched it off, or
repeat "tidak ada koneksi" every few seconds through an outage. And the button
side: ACTION in explorer is now the switch, every other mode keeps its capture.
"""

import types

import pytest

import adapters
import config as config_mod
from config import cfg
from core import orchestrator as orch_mod
from core.orchestrator import Orchestrator
from modes import explorer_mode
from modes.scan_narrator import ScanNarrator


class _Audio:
    """Records what the user would have heard; `quiet` is the playback state."""

    def __init__(self):
        self.events = []
        self.spoken = []
        self.quiet = True

    def is_quiet(self):
        return self.quiet

    def speak_scene(self, text, scene_id=None, still_wanted=None):
        self.spoken.append(text)
        self.still_wanted = still_wanted
        self.quiet = False

    def queue_system(self, event):
        self.events.append(event)

    def user_barge_in(self, cue_wav="chime_press.wav"):
        pass

    def queue_cue(self, wav_name, priority=None, label=None):
        pass

    def queue_info(self, text):
        self.events.append(("info", text))

    def clear(self):
        pass

    def stop(self):
        pass


class _Logger:
    def info(self, *a, **k):      pass
    def ok(self, *a, **k):        pass
    def warn(self, *a, **k):      pass
    def error(self, *a, **k):     pass
    def debug(self, *a, **k):     pass
    def exception(self, *a, **k): pass


class _Engine:
    def __init__(self, jpeg=b"\xff\xd8jpeg"):
        self.jpeg = jpeg

    def _frame_jpeg(self):
        return self.jpeg


class _Clock:
    def __init__(self, t=100.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def cfgset():
    saved = {}

    def _set(key, value):
        saved.setdefault(key, cfg.get(key))
        cfg.set(key, value)

    yield _set
    for key, value in saved.items():
        cfg.set(key, value)


@pytest.fixture
def cloud(monkeypatch):
    """A scripted vision API: each call pops the next answer (or raises it)."""
    answers = []
    calls = []

    class _Adapter:
        def describe_scene(self, jpeg, prompt):
            calls.append(prompt)
            a = answers.pop(0) if answers else "Lorong lurus di depan."
            if isinstance(a, Exception):
                raise a
            return a

    monkeypatch.setattr(adapters, "get_adapter", lambda *a, **k: _Adapter())
    return types.SimpleNamespace(answers=answers, calls=calls)


@pytest.fixture
def rig(cfgset, cloud):
    """A narrator wired to fakes; spawned calls wait until run() is called."""
    cfgset("scan_interval_s", 8)
    cfgset("scan_stale_s", 6)
    cfgset("scan_retry_s", 15)
    cfgset("audio_mode", "both")
    cfgset("tts_enabled", True)
    clock = _Clock()
    pending = []
    orch = types.SimpleNamespace(audio_manager=_Audio(), ai_engine=_Engine(),
                                 logger=_Logger())
    n = ScanNarrator(orch, clock=clock, spawn=pending.append)

    def run():
        while pending:
            pending.pop(0)()

    return types.SimpleNamespace(n=n, orch=orch, am=orch.audio_manager,
                                 clock=clock, pending=pending, run=run,
                                 cloud=cloud)


# ── The narrator ─────────────────────────────────────────────────────────────

def test_switched_off_it_never_calls_the_cloud(rig):
    rig.n.step()
    assert rig.pending == []


def test_first_photo_waits_for_the_switch_on_phrase_to_finish(rig):
    rig.n.start()
    rig.am.quiet = False              # "navigasi daring aktif" still playing
    rig.n.step()
    assert rig.pending == []
    rig.am.quiet = True
    rig.n.step()
    assert len(rig.pending) == 1


def test_answer_is_spoken_and_holds_the_floor_until_it_has_played(rig):
    rig.n.start()
    rig.n.step()
    rig.cloud.answers.append("Tangga turun di depan, dekat.")
    rig.clock.t += 2.5
    rig.run()
    assert rig.am.spoken == ["Tangga turun di depan, dekat."]
    assert rig.n.holds_floor()
    rig.am.quiet = True
    rig.n.step()
    assert not rig.n.holds_floor()


@pytest.mark.parametrize("answer", ["Belum ada yang perlu disebut.",
                                    "belum ada yang perlu disebut",
                                    "Belum ada yang perlu disebut. "])
def test_nothing_to_report_is_not_read_out(rig, answer):
    # The prompt's marker for an empty scene. Spoken, it was the same awkward
    # sentence every ~8 s on a quiet walk.
    rig.n.start()
    rig.n.step()
    rig.cloud.answers.append(answer)
    rig.clock.t += 2.0
    rig.run()
    assert rig.am.spoken == []
    assert not rig.n.holds_floor()


def test_a_real_answer_that_merely_mentions_belum_is_still_spoken(rig):
    rig.n.start()
    rig.n.step()
    rig.cloud.answers.append("Belum ada tangga; pintu di kanan, dekat.")
    rig.clock.t += 2.0
    rig.run()
    assert rig.am.spoken == ["Belum ada tangga; pintu di kanan, dekat."]


def test_one_call_in_flight_and_the_interval_is_a_floor(rig):
    rig.n.start()
    rig.n.step()
    assert len(rig.pending) == 1
    rig.clock.t += 20                 # long past the interval, still in flight
    rig.n.step()
    assert len(rig.pending) == 1      # never a second request on top
    rig.run()                         # lands stale: dropped
    rig.n.step()                      # the interval has long elapsed
    assert len(rig.pending) == 1


def test_next_photo_not_before_the_interval_even_when_quiet(rig):
    rig.n.start()
    rig.n.step()
    rig.clock.t += 2
    rig.run()                         # speaks
    rig.am.quiet = True
    rig.clock.t += 3                  # 5 s since the photo, interval is 8
    rig.n.step()
    assert rig.pending == []
    rig.clock.t += 3                  # 8 s
    rig.n.step()
    assert len(rig.pending) == 1


def test_next_photo_waits_for_the_sentence_even_past_the_interval(rig):
    rig.n.start()
    rig.n.step()
    rig.clock.t += 2
    rig.run()                         # speaking now
    rig.clock.t += 30
    rig.n.step()
    assert rig.pending == []          # never talks over itself


def test_a_stale_answer_is_dropped_unspoken(rig):
    rig.n.start()
    rig.n.step()
    rig.clock.t += 7                  # stale_s is 6
    rig.run()
    assert rig.am.spoken == []


def test_an_answer_landing_after_switch_off_is_never_spoken(rig):
    rig.n.start()
    rig.n.step()
    rig.n.stop()
    rig.n.start()                     # back on before the old call returned
    rig.n.step()
    assert len(rig.pending) == 1      # the old call is still the only one
    rig.clock.t += 1
    rig.run()                         # … and it lands now
    assert rig.am.spoken == []


def test_a_switch_off_during_the_render_cancels_the_sentence(rig):
    """speak_scene takes ~0.7 s (concat) to 3 s (gTTS) before anything is
    queued; a press in that window must still win."""
    rig.n.start()
    rig.n.step()
    rig.run()
    assert rig.am.still_wanted() is True
    rig.n.stop()
    assert rig.am.still_wanted() is False


def test_a_failure_is_spoken_once_per_outage_then_backs_off(rig):
    down = adapters.AdapterError("<urlopen error [Errno -3] Temporary failure in name resolution>")
    rig.cloud.answers.extend([down, down, "Pintu di kanan."])
    rig.n.start()
    rig.n.step()
    rig.run()
    assert rig.am.events == ["tidak_ada_koneksi"]

    rig.clock.t += 9                  # interval passed, retry_s (15) has not
    rig.n.step()
    assert rig.pending == []
    rig.clock.t += 6
    rig.n.step()
    rig.run()
    assert rig.am.events == ["tidak_ada_koneksi"]     # not again

    rig.clock.t += 15
    rig.n.step()
    rig.run()
    assert rig.am.spoken == ["Pintu di kanan."]


def test_chime_only_mode_pays_for_no_calls(rig, cfgset):
    cfgset("audio_mode", "chime")
    rig.n.start()
    rig.n.step()
    assert rig.pending == []


def test_no_frame_no_call(rig):
    rig.orch.ai_engine = _Engine(jpeg=b"")
    rig.n.start()
    rig.n.step()
    assert rig.pending == []


def test_it_asks_with_the_scan_prompt(rig):
    rig.n.start()
    rig.n.step()
    rig.run()
    assert rig.cloud.calls == [cfg.PROMPT_SCAN]


@pytest.mark.parametrize("raw,want", [
    (8, 8.0), (0, 3.0), (-5, 3.0), (999, 60.0), ("12", 12.0),
    ("abc", 8.0), (None, 8.0), (float("nan"), 8.0),
])
def test_interval_is_clamped_at_the_read_site(cfgset, raw, want):
    cfgset("scan_interval_s", raw)
    assert cfg.SCAN_INTERVAL_S == want


# ── Explorer keeps hazards, drops chatter, while a narration plays ───────────

def test_explorer_speaks_only_hazards_while_the_narration_holds_the_floor():
    heard = []
    dets = [{"label": "person", "tier": "far"},
            {"label": "car", "tier": "near"}]
    orch = types.SimpleNamespace(
        ai_engine=types.SimpleNamespace(
            capture_and_infer=lambda: (None, list(dets), {})),
        audio_manager=types.SimpleNamespace(
            announce_detections=lambda d, force=False: heard.append(list(d))),
        scan=types.SimpleNamespace(step=lambda: None, holds_floor=lambda: True),
        detection_audio_suppressed=lambda: False,
        detections=[], latency={},
    )
    explorer_mode.run_explorer_tick(orch)
    assert heard == [[{"label": "car", "tier": "near"}]]


def test_explorer_runs_the_narrator_even_on_an_empty_frame():
    stepped = []
    orch = types.SimpleNamespace(
        ai_engine=types.SimpleNamespace(capture_and_infer=lambda: (None, [], {})),
        audio_manager=None,
        scan=types.SimpleNamespace(step=lambda: stepped.append(1),
                                   holds_floor=lambda: False),
        detection_audio_suppressed=lambda: False,
        detections=[], latency={},
    )
    explorer_mode.run_explorer_tick(orch)
    assert stepped == [1]


# ── The button ───────────────────────────────────────────────────────────────

@pytest.fixture
def orch(tmp_path, monkeypatch, cfgset):
    monkeypatch.setattr(config_mod, "_CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(orch_mod, "ai_key_present", lambda: True)
    cfgset("button_pin_mode", "")
    cfgset("button_pin_action", "")
    cfgset("setup_completed", True)
    o = Orchestrator(_Logger())
    o.audio_manager = _Audio()
    o._mode = "explorer"
    yield o
    o._running = False


def test_action_in_explorer_switches_online_navigation_on_then_off(orch):
    orch._on_action_button(long_press=False, in_volume=False)
    assert orch.scan.active
    assert orch.audio_manager.events[-1] == "navigasi_daring_aktif"
    assert orch.pop_pending_command() is None      # no one-off describe any more

    orch._on_action_button(long_press=False, in_volume=False)
    assert not orch.scan.active
    assert orch.audio_manager.events[-1] == "navigasi_daring_mati"


@pytest.mark.parametrize("mode,cmd", [("context", "describe")])
def test_action_outside_explorer_still_captures(orch, mode, cmd):
    orch._mode = mode
    orch._on_action_button(long_press=False, in_volume=False)
    assert not orch.scan.active
    assert orch.pop_pending_command()["cmd"] == cmd


def test_long_action_in_explorer_still_repeats_the_last_result(orch):
    orch.audio_manager.last_caption = {"text": "Pintu di kanan."}
    orch._on_action_button(long_press=True, in_volume=False)
    assert not orch.scan.active
    assert orch.audio_manager.events == [("info", "Pintu di kanan.")]


def test_without_an_api_key_it_says_so_and_stays_off(orch, monkeypatch):
    monkeypatch.setattr(orch_mod, "ai_key_present", lambda: False)
    orch._on_action_button(long_press=False, in_volume=False)
    assert not orch.scan.active
    assert orch.audio_manager.events == ["api_tidak_tersedia"]


def test_leaving_explorer_switches_it_off_without_a_second_phrase(orch):
    orch.toggle_scan()
    orch.audio_manager.events.clear()
    orch.switch_mode("context")
    assert not orch.scan.active
    assert "navigasi_daring_mati" not in orch.audio_manager.events


def test_status_reports_the_switch_and_the_interval(orch, cfgset):
    cfgset("scan_interval_s", 0)
    orch.toggle_scan()
    s = orch.get_status()
    assert s["scan_active"] is True
    assert s["scan_interval_s"] == 3.0


# ── AudioManager.is_quiet, the gate the narrator waits on ────────────────────

@pytest.fixture
def real_am(tmp_path, monkeypatch):
    import core.audio_manager as am_mod

    class _Null:
        def __getattr__(self, _name):
            return lambda *a, **k: None

    monkeypatch.setattr(cfg, "_data", {**cfg._data, "word_cache_dir": str(tmp_path)})
    mgr = am_mod.AudioManager(orchestrator=None, logger=_Null())
    yield mgr
    mgr.stop()


def _wait(pred, timeout=2.0):
    end = __import__("time").monotonic() + timeout
    while __import__("time").monotonic() < end:
        if pred():
            return True
        __import__("time").sleep(0.01)
    return pred()


def test_is_quiet_follows_playback(real_am, monkeypatch):
    import threading
    release = threading.Event()
    monkeypatch.setattr(real_am, "_play_pcm_bytes",
                        lambda pcm: release.wait(2.0) or True)
    assert real_am.is_quiet()
    real_am.queue_pcm_bytes(b"\x00\x00" * 480, "Pintu di kanan.")
    assert _wait(lambda: real_am.current_text == "Pintu di kanan.")
    assert not real_am.is_quiet()
    release.set()
    assert _wait(real_am.is_quiet)


def test_a_playback_that_raises_does_not_leave_it_speaking_forever(real_am, monkeypatch):
    """Seen on isora-88dd: one exception inside _play_task skipped the reset of
    _current_text, is_quiet() stayed False, and the narrator never took another
    photo. The loop must clear it on the error path too."""
    def _boom(pcm):
        raise RuntimeError("signal only works in main thread")
    monkeypatch.setattr(real_am, "_play_pcm_bytes", _boom)
    real_am.queue_pcm_bytes(b"\x00\x00" * 480, "Pintu di kanan.")
    assert _wait(real_am.is_quiet)


@pytest.mark.parametrize("cached", [True, False], ids=["concat", "synth"])
def test_speak_scene_drops_a_sentence_no_longer_wanted(real_am, monkeypatch, tmp_path,
                                                      cached, wanted=False):
    """Both render paths ask still_wanted() before queueing anything."""
    import time as _t
    from utils.word_cache import tokenize
    text = "Pintu di kanan"
    played = []
    monkeypatch.setattr(real_am, "_play_pcm_bytes",
                        lambda data: played.append(bytes(data)) or True)
    monkeypatch.setattr(cfg, "_data", {**cfg._data, "word_cache_trim_enabled": False,
                                       "word_cache_max_words": 0})
    if cached:
        for w in tokenize(text):
            assert real_am._word_cache.store(w, w.encode() * 4)
    else:
        pcm = tmp_path / "chunk.pcm"
        pcm.write_bytes(bytes([1, 0]) * 480)
        monkeypatch.setattr(real_am, "_render_pcm", lambda chunk: str(pcm))
        monkeypatch.setattr(real_am, "_warm_words_async", lambda words: None)
    real_am.speak_scene(text, still_wanted=lambda: wanted)
    _t.sleep(0.2)
    assert _wait(real_am.is_quiet)
    assert bool(played) is wanted


@pytest.mark.parametrize("cached", [True, False], ids=["concat", "synth"])
def test_speak_scene_still_plays_a_wanted_sentence(real_am, monkeypatch, tmp_path, cached):
    """The control: same set-up, still wanted — so the drop above is the guard
    working, not a set-up that can never play."""
    test_speak_scene_drops_a_sentence_no_longer_wanted(
        real_am, monkeypatch, tmp_path, cached, wanted=True)

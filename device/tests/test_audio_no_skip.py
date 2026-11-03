"""No clip the program asks for may go missing by accident.

Two halves. Static: every cue the code can request has a pre-recorded source in
tools/generate_audio.py, so nothing silently depends on gTTS (which is exactly
what fails offline, on a venue network). Dynamic: the play loop no longer loses
a clip that was talked over by a more urgent one, no longer swallows an urgent
alert queued in the instant a clip starts, keeps the recording when "speech"
mode cannot reach TTS, and retries a driver error once.
"""

import importlib.util
import os
import re
import sys
import time
import types

import pytest

import core.audio_manager as am_mod
from core.audio_manager import CRITICAL, LOW, NORMAL

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_DEVICE = os.path.join(_REPO, "device")
_GEN = os.path.join(_REPO, "tools", "generate_audio.py")


# ─── Static coverage ─────────────────────────────────────────────────────────

def _gen():
    spec = importlib.util.spec_from_file_location("isora_gen_audio_cov", _GEN)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _safe(text):
    s = text.lower().strip().replace(" ", "_").replace("-", "_").replace(",", "")
    return "".join(c for c in s if c.isalnum() or c == "_")


def _sources():
    out = []
    for root, _, names in os.walk(_DEVICE):
        if os.sep + "tests" in root or "benchmark" in root:
            continue
        for n in names:
            if n.endswith(".py") and n not in ("benchmark.py", "overnight_stress.py"):
                p = os.path.join(root, n)
                out.append((os.path.relpath(p, _REPO), open(p, encoding="utf-8").read()))
    return out


def _generated_names():
    g = _gen()
    names = {fn for fn, _ in g.build_audio_list()}
    # `generate_audio.py --from-wordlist` is the other source of speech files.
    names |= {fn for fn, _ in g.parse_wordlist_markdown(g.WORDLIST_DEFAULT)}
    names |= {f"{k}.wav" for k in g.CHIMES}
    return names


def _resolves(names, text, wav_name=None):
    s = _safe(text)
    cands = ([wav_name] if wav_name else []) + [f"{s}.wav", f"obj_{s}.wav", f"system_{s}.wav"]
    return any(c in names for c in cands)


def test_every_system_cue_the_code_requests_is_pre_generated():
    from core.orchestrator import Orchestrator
    from utils.money import cue_key

    names = _generated_names()
    keys = set()
    for _, text in _sources():
        keys |= set(re.findall(r"queue_system\(\s*[\"']([^\"']+)[\"']", text))
        keys |= set(re.findall(r"_net_failure_cue\([^,]+,\s*[\"']([^\"']+)[\"']", text))
    keys |= {"tidak_ada_koneksi", "koneksi_lambat", "masih_memproses"}
    keys |= {f"mode_{m}" for m in Orchestrator.MODES}
    # The banknote model's classes (uang_yolo26n.mud): 1K..100K.
    keys |= {cue_key(v) for v in (1000, 2000, 5000, 10000, 20000, 50000, 100000)}
    missing = sorted(k for k in keys
                     if not _resolves(names, k.replace("_", " "), f"{k}.wav"))
    assert not missing, "no pre-recorded WAV (silent offline): %s" % missing


def test_every_sentence_queued_by_text_is_pre_generated():
    names = _generated_names()
    missing = []
    for rel, text in _sources():
        for m in re.finditer(r"\.queue\(\s*[\"']([^\"']+)[\"'](?P<rest>[^)]*)\)", text):
            wav = re.search(r"wav_name=[\"']([^\"']+)[\"']", m.group("rest"))
            if wav:
                continue  # explicit file, checked on the unit by the QA script
            if not _resolves(names, m.group(1)):
                missing.append((rel, m.group(1)))
    assert not missing, missing


def test_every_cue_file_the_code_plays_is_a_known_chime_or_boot_line():
    g = _gen()
    chimes = {f"{k}.wav" for k in g.CHIMES}
    used = set()
    for _, text in _sources():
        used |= set(re.findall(r"(?:queue_cue|user_barge_in)\(\s*[\"']([^\"']+)[\"']", text))
    # The boot lines come from the brand assets, not the generator (BRANDING.md).
    unknown = sorted(u for u in used if u not in chimes and not u.startswith("isora_"))
    assert not unknown, unknown


# ─── Play loop ───────────────────────────────────────────────────────────────

class _Log:
    def __getattr__(self, _n):
        return lambda *a, **k: None


@pytest.fixture
def am(tmp_path, monkeypatch):
    from config import cfg
    monkeypatch.setattr(cfg, "_data", {**cfg._data, "word_cache_dir": str(tmp_path),
                                       "audio_mode": "both", "tts_provider": "gtts"})
    mgr = am_mod.AudioManager(orchestrator=None, logger=_Log())
    mgr._stop.set()            # park the real loop; tests drive _play_task
    mgr._thread.join(timeout=1)
    mgr._stop.clear()
    # Every clip is "a file": pcm resolution just hands back the text.
    monkeypatch.setattr(mgr, "_ensure_pcm", lambda wav, nice=False: wav)
    monkeypatch.setattr(mgr, "_render_pcm", lambda text: None)
    real_open = open

    def fake_open(path, mode="r", *a, **k):
        if "b" in mode and str(path).startswith("pcm:"):
            import io
            return io.BytesIO(b"\x00\x01" * 100)
        return real_open(path, mode, *a, **k)
    monkeypatch.setattr("builtins.open", fake_open)
    yield mgr
    mgr.stop()


def _task(text, prio=NORMAL, label="", cue=False):
    return am_mod._Task(text, "pcm:" + text, prio, label, is_cue=cue)


def _drain(mgr):
    out = []
    while not mgr._pq.empty():
        out.append(mgr._pq.get_nowait()[2])
    return out


def test_a_clip_talked_over_by_an_alert_is_played_again(am, monkeypatch):
    mode = _task("mode jelajah", NORMAL, "sys_mode_explorer")
    am._enqueue(mode)
    am._pq.get_nowait()

    def play(_pcm):
        # An obstacle alert lands mid-sentence.
        am._enqueue(_task("orang di depan", CRITICAL, "nav_person_center"))
        am._cut_short = True
        return True
    monkeypatch.setattr(am, "_play_pcm_bytes", play)
    am._play_task(mode)
    order = [t.text for t in sorted(_drain(am))]
    assert order == ["orang di depan", "mode jelajah"]


def test_a_clip_cancelled_by_a_press_is_not_played_again(am, monkeypatch):
    desc = _task("Seorang pria berdiri.", LOW)
    am._enqueue(desc)
    am._pq.get_nowait()

    def play(_pcm):
        am.clear()             # the user pressed a button
        am._cut_short = True
        return True
    monkeypatch.setattr(am, "_play_pcm_bytes", play)
    am._play_task(desc)
    assert _drain(am) == []


def test_a_task_cancelled_after_the_loop_took_it_never_starts(am, monkeypatch):
    played = []
    monkeypatch.setattr(am, "_play_pcm_bytes", lambda pcm: played.append(pcm) or True)
    t = _task("sisa deskripsi", LOW)
    am._enqueue(t)
    am._pq.get_nowait()        # the loop has it ...
    am.clear()                 # ... and then the press lands
    am._play_task(t)
    assert played == []


def test_replays_are_bounded(am, monkeypatch):
    t = _task("mode konteks", NORMAL, "sys_mode_context")

    def play(_pcm):
        am._cut_short = True
        return True
    monkeypatch.setattr(am, "_play_pcm_bytes", play)
    plays = 0
    am._enqueue(t)
    while not am._pq.empty():
        task = am._pq.get_nowait()[2]
        am._play_task(task)
        plays += 1
        assert plays < 10
    assert plays == 1 + am_mod._MAX_REPLAYS


def test_cues_are_not_replayed(am, monkeypatch):
    def play(_pcm):
        am._cut_short = True
        return True
    monkeypatch.setattr(am, "_play_pcm_bytes", play)
    am._play_task(_task("chime_press.wav", CRITICAL, "user_press", cue=True))
    assert _drain(am) == []


def test_an_alert_queued_as_a_clip_starts_still_interrupts_it(am, monkeypatch):
    seen = {}

    def play(_pcm):
        seen["interrupt"] = am._interrupt.is_set()
        return True
    monkeypatch.setattr(am, "_play_pcm_bytes", play)
    long_chunk = _task("kalimat panjang deskripsi", LOW)
    am._enqueue(long_chunk)
    am._pq.get_nowait()
    # Arrives while the loop is between get() and starting playback, while
    # _current_priority still reads LOW from the previous clip.
    am._enqueue(_task("motor di kiri dekat", CRITICAL, "nav_motorcycle_left"))
    am._interrupt.clear()      # what the old code did right here
    am._play_task(long_chunk)
    assert seen["interrupt"] is True


def test_a_finished_clip_is_not_replayed_just_because_an_alert_followed(am, monkeypatch):
    def play(_pcm):
        return True            # played to the end
    monkeypatch.setattr(am, "_play_pcm_bytes", play)
    t = _task("mode jelajah", NORMAL, "sys_mode_explorer")
    am._enqueue(t)
    am._pq.get_nowait()
    am._play_task(t)
    am._enqueue(_task("orang di depan", CRITICAL))   # arrives after the end
    assert [x.text for x in _drain(am)] == ["orang di depan"]


def test_speech_mode_offline_falls_back_to_the_recording(am, monkeypatch):
    from config import cfg
    monkeypatch.setitem(cfg._data, "audio_mode", "speech")
    played = []
    monkeypatch.setattr(am, "_play_pcm_bytes", lambda pcm: played.append(pcm) or True)
    am._play_task(_task("gagal memindai", NORMAL, "sys_gagal_memindai"))
    assert played, "TTS unreachable + a WAV on disk must not mean silence"


def test_a_driver_error_is_retried_once(am, monkeypatch):
    calls = []

    def play(_pcm):
        calls.append(1)
        if len(calls) == 1:
            am._play_failed = True
            return False
        return True
    monkeypatch.setattr(am, "_play_pcm_bytes", play)
    am._play_task(_task("isora siap digunakan", NORMAL))
    assert len(calls) == 2


def test_no_retry_when_there_is_simply_no_player(am, monkeypatch):
    calls = []
    monkeypatch.setattr(am, "_play_pcm_bytes", lambda pcm: calls.append(1) or False)
    am._play_task(_task("x", NORMAL))
    assert len(calls) == 1


# ─── PCM cache ───────────────────────────────────────────────────────────────

def test_prewarm_converts_stale_clips_and_skips_fresh_ones(tmp_path, monkeypatch):
    from config import cfg
    monkeypatch.setattr(cfg, "_data", {**cfg._data, "word_cache_dir": str(tmp_path / "wc")})
    mgr = am_mod.AudioManager(orchestrator=None, logger=_Log())
    try:
        mgr._audio_dir = str(tmp_path)
        for n in ("chime_press.wav", "system_x.wav", "obj_a.wav"):
            (tmp_path / n).write_bytes(b"RIFF")
        fresh = tmp_path / "obj_a.pcm"
        fresh.write_bytes(b"\0\0")
        st = os.stat(tmp_path / "obj_a.wav")
        os.utime(fresh, (st.st_atime, st.st_mtime))
        done = []
        monkeypatch.setattr(mgr, "_ensure_pcm",
                            lambda wav, nice=False: done.append((os.path.basename(wav), nice)) or wav)
        mgr.prewarm_pcm_cache(delay_s=0)
        deadline = time.monotonic() + 3
        while len(done) < 2 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert done == [("chime_press.wav", True), ("system_x.wav", True)]
    finally:
        mgr.stop()


def test_a_failed_conversion_leaves_no_partial_pcm(tmp_path, monkeypatch):
    from config import cfg
    monkeypatch.setattr(cfg, "_data", {**cfg._data, "word_cache_dir": str(tmp_path / "wc")})
    mgr = am_mod.AudioManager(orchestrator=None, logger=_Log())
    try:
        wav = tmp_path / "chime_x.wav"
        wav.write_bytes(b"RIFF")

        def fake_run(cmd, **kw):
            open(cmd[-1], "wb").write(b"half")   # ffmpeg wrote some, then failed
            return types.SimpleNamespace(returncode=1)
        monkeypatch.setattr("subprocess.run", fake_run)
        assert mgr._ensure_pcm(str(wav)) is None
        assert sorted(os.listdir(tmp_path)) == ["chime_x.wav", "wc"]
    finally:
        mgr.stop()


def test_deploy_keeps_local_mtimes(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "isora_deploy_t", os.path.join(_REPO, "tools", "deploy.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    (tmp_path / "a.wav").write_bytes(b"x")
    os.utime(tmp_path / "a.wav", (1_700_000_000, 1_700_000_000))
    calls = []
    sftp = types.SimpleNamespace(mkdir=lambda p: None,
                                 put=lambda l, r: calls.append(("put", r)),
                                 utime=lambda r, t: calls.append(("utime", r, t[1])))
    mod.deploy_directory(sftp, str(tmp_path), "/root/audio")
    assert ("utime", "/root/audio/a.wav", 1_700_000_000) in calls


# ─── Audio trace (GET /audio/trace) ──────────────────────────────────────────

def _events(mgr, since=0):
    return [(e["event"], e["text"], e["reason"]) for e in mgr.trace_since(since)["events"]]


def test_trace_follows_a_clip_from_queue_to_played(am, monkeypatch):
    monkeypatch.setattr(am, "_play_pcm_bytes", lambda pcm: True)
    t = _task("mode jelajah", NORMAL, "sys_mode_explorer")
    am._enqueue(t)
    am._play_task(am._pq.get_nowait()[2])
    assert _events(am) == [("queued", "mode jelajah", ""), ("played", "mode jelajah", "")]


def test_trace_says_why_a_clip_never_sounded(am, monkeypatch):
    monkeypatch.setattr(am, "_play_pcm_bytes", lambda pcm: True)
    am.queue("gagal memindai", label="sys_gagal_memindai", cooldown=5, wav_name="x.wav")
    am._play_task(am._pq.get_nowait()[2])
    am.queue("gagal memindai", label="sys_gagal_memindai", cooldown=5, wav_name="x.wav")
    am._enqueue(_task("sisa deskripsi", LOW))
    am.clear()
    ev = _events(am)
    assert ("dropped", "gagal memindai", "cooldown") in ev
    assert ("dropped", "sisa deskripsi", "flushed") in ev


def test_trace_marks_a_clip_that_was_cut_and_replayed(am, monkeypatch):
    def play(_pcm):
        am._cut_short = True
        return True
    monkeypatch.setattr(am, "_play_pcm_bytes", play)
    am._enqueue(_task("mode konteks", NORMAL))
    am._play_task(am._pq.get_nowait()[2])
    assert _events(am)[-1] == ("cut", "mode konteks", "")
    assert not am._pq.empty()        # and it is waiting to play again


def test_trace_since_returns_only_newer_entries(am):
    am._note("queued", "a")
    seq = am.trace_since()["seq"]
    am._note("queued", "b")
    assert [e["text"] for e in am.trace_since(seq)["events"]] == ["b"]


def test_an_empty_pcm_is_never_fresh_even_with_the_right_stamp(tmp_path):
    # aural-78a7 had a 0-byte system_mode_idle.pcm stamped with its WAV's
    # mtime: switching to idle said nothing, and the prewarm skipped it.
    wav, pcm = tmp_path / "system_mode_idle.wav", tmp_path / "system_mode_idle.pcm"
    wav.write_bytes(b"RIFF....")
    pcm.write_bytes(b"")
    st = os.stat(wav)
    os.utime(pcm, (st.st_atime, st.st_mtime))
    assert am_mod._pcm_is_fresh(str(wav), str(pcm)) is False
    pcm.write_bytes(b"\x00\x01")
    os.utime(pcm, (st.st_atime, st.st_mtime))
    assert am_mod._pcm_is_fresh(str(wav), str(pcm)) is True

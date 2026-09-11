"""Scene descriptions are spoken one sentence at a time, rendered off the play loop.

What this pins down (the whole point of the change): the gTTS round-trip for a
scene description must NOT happen inside the playback loop, where it could only
start after the success chime ahead of it had finished, and must NOT be one call
for the whole description, because gTTS time scales with text length. Chunk 1 is
rendered on a background thread and queued as soon as it is ready, so the user
hears the opening sentence while the tail is still being synthesized.

Only synthesis and the maix playback call are stubbed; the priority queue, the
loop thread, the splitter and the generation guard are all real.
"""

import time

import pytest

import core.audio_manager as am_mod
from core.audio_manager import split_sentences
from utils.scene_metrics import SceneMetrics

TWO_SENTENCES = ("Seorang pria berdiri di dalam ruangan kantor. "
                 "Di depannya ada meja komputer.")


class _NullLogger:
    def __getattr__(self, _name):
        return lambda *a, **k: None


@pytest.fixture
def am(tmp_path, monkeypatch):
    from config import cfg
    monkeypatch.setattr(cfg, "_data", {**cfg._data,
                                       "word_cache_dir": str(tmp_path),
                                       "tts_provider": "gtts",
                                       "scene_stream_chunks": 3})
    mgr = am_mod.AudioManager(orchestrator=None, logger=_NullLogger())
    # Never let a real describe reach the network from a unit test.
    monkeypatch.setattr(mgr, "_warm_words_async", lambda words: None)
    yield mgr
    mgr.stop()


def _stub_render(am, monkeypatch, spoken, synth_delay=0.0, on_synth=None):
    """Fake rendering; `spoken` collects what the play loop actually dequeued."""
    synthesized = []

    def _render(text):
        if synth_delay:
            time.sleep(synth_delay)
        synthesized.append(text)
        if on_synth:
            on_synth(text)
        return "/tmp/%s.pcm" % abs(hash(text))

    monkeypatch.setattr(am, "_render_pcm", _render)
    monkeypatch.setattr(am, "_play_task", lambda task: spoken.append(task.text))
    return synthesized


def _wait(pred, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.02)
    return False


def test_semicolon_is_a_chunk_boundary():
    # The vision models routinely join two clauses with ';' — without this the
    # whole description would be one un-splittable gTTS call.
    text = "Tidak tampak orang; area di depan tertutup kabut."
    assert split_sentences(text) == ["Tidak tampak orang;",
                                     "area di depan tertutup kabut."]


def test_description_is_synthesized_in_order_one_sentence_at_a_time(am, monkeypatch):
    synthesized = _stub_render(am, monkeypatch, spoken=[])

    am.speak_scene(TWO_SENTENCES)

    assert _wait(lambda: len(synthesized) == 2), synthesized
    assert synthesized == ["Seorang pria berdiri di dalam ruangan kantor.",
                           "Di depannya ada meja komputer."]


def test_first_chunk_plays_without_waiting_for_the_tail(am, monkeypatch):
    """The whole win: chunk 1 must reach the speaker while chunk 2 is still
    rendering, not after it."""
    spoken = []
    done = []

    def _slow_tail(text):
        # Chunk 2 takes far longer than chunk 1 to come back.
        if text.startswith("Di depannya"):
            time.sleep(0.4)
        done.append(text)
        return "/tmp/%s.pcm" % abs(hash(text))

    monkeypatch.setattr(am, "_render_pcm", _slow_tail)
    monkeypatch.setattr(am, "_play_task", lambda task: spoken.append(task.text))

    am.speak_scene(TWO_SENTENCES)

    assert _wait(lambda: spoken, timeout=1.0), "chunk 1 never played"
    assert spoken == ["Seorang pria berdiri di dalam ruangan kantor."]
    assert "Di depannya ada meja komputer." not in done, (
        "chunk 1 waited for the tail to finish rendering")


def test_chunks_render_concurrently_not_one_after_another(am, monkeypatch):
    """Rendered serially the tail arrived at chunk1+chunk2 — sometimes after
    chunk 1 had finished playing, an audible gap mid-sentence."""
    inflight = []
    peak = []

    def _render(text):
        inflight.append(text)
        peak.append(len(inflight))
        time.sleep(0.25)
        inflight.remove(text)
        return "/tmp/%s.pcm" % abs(hash(text))

    monkeypatch.setattr(am, "_render_pcm", _render)
    monkeypatch.setattr(am, "_play_task", lambda task: None)

    am.speak_scene(TWO_SENTENCES)

    assert _wait(lambda: len(peak) == 2), peak
    assert max(peak) == 2, "renders were serialized"


def test_scene_stream_chunks_1_restores_one_whole_sentence_synth(am, monkeypatch):
    from config import cfg
    monkeypatch.setattr(cfg, "_data", {**cfg._data, "scene_stream_chunks": 1})
    synthesized = _stub_render(am, monkeypatch, spoken=[])

    am.speak_scene(TWO_SENTENCES)

    assert _wait(lambda: len(synthesized) == 1), synthesized
    assert synthesized == [TWO_SENTENCES]


def test_barge_in_drops_the_rest_of_an_abandoned_description(am, monkeypatch):
    """A press mid-description must not be followed by its leftover tail.

    Chunks render concurrently, so a render already in flight is paid for
    either way — an HTTP round-trip can't be recalled. What must not happen is
    that its audio then reaches the queue and plays over whatever the user
    pressed for.
    """
    spoken = []

    def _on_synth(text):
        if text.startswith("Seorang pria"):
            am.clear()          # user barges in while chunk 1 is rendering

    _stub_render(am, monkeypatch, spoken, on_synth=_on_synth)

    am.speak_scene(TWO_SENTENCES)

    time.sleep(0.5)
    assert spoken == [], "abandoned description still reached the play loop"
    assert am._pq.qsize() == 0, "abandoned chunk was still queued"


def test_metrics_report_time_to_first_word_not_to_whole_description(am, monkeypatch):
    metrics = SceneMetrics(now_iso=lambda: "2026-01-01T00:00:00")
    monkeypatch.setattr(am_mod, "scene_metrics", metrics)
    _stub_render(am, monkeypatch, spoken=[], synth_delay=0.1)

    sid = metrics.start_describe(TWO_SENTENCES, "detail", 4200)
    am.speak_scene(TWO_SENTENCES, scene_id=sid)

    assert _wait(lambda: metrics.snapshot()["last"]["to_audio_ms"] is not None)
    time.sleep(0.4)   # let the tail land and update audio_ms
    last = metrics.snapshot()["last"]
    # ~one chunk of synth, not two — that is what the user actually waited for.
    assert last["to_audio_ms"] < 200, last


# ─── TTS backend selection ────────────────────────────────────────────────────

def test_openai_backend_speaks_the_sentence_whole_not_from_the_word_cache(
        am, monkeypatch):
    """Warmed words are rendered by whatever backend was active when they were
    warmed, so splicing them under a different one would switch voice
    mid-session. The openai path renders the sentence in one piece instead."""
    from config import cfg
    monkeypatch.setattr(cfg, "_data", {**cfg._data, "tts_provider": "openai",
                                       "openai_api_key": "sk-test"})
    spoken = []
    _stub_render(am, monkeypatch, spoken)

    def _no_concat(*a, **k):
        raise AssertionError("word-cache concat ran on the openai backend")
    monkeypatch.setattr(am_mod, "plan_utterance", _no_concat)

    am.speak_scene(TWO_SENTENCES)
    assert _wait(lambda: len(spoken) == 2), spoken


def test_render_pcm_falls_back_to_gtts_when_openai_tts_fails(am, monkeypatch):
    """No network / bad key must degrade to the slower voice, never to silence."""
    from config import cfg
    monkeypatch.setattr(cfg, "_data", {**cfg._data, "tts_provider": "openai",
                                       "openai_api_key": "sk-test"})
    monkeypatch.setattr("utils.tts.get_or_synthesize_pcm",
                        lambda *a, **k: None)
    gtts_calls = []
    monkeypatch.setattr(am, "_tts_synthesize",
                        lambda text: gtts_calls.append(text) or "/tmp/x.wav")
    monkeypatch.setattr(am, "_ensure_pcm", lambda wav: "/tmp/x.pcm")

    assert am._render_pcm("halo dunia") == "/tmp/x.pcm"
    assert gtts_calls == ["halo dunia"]


def test_tts_provider_auto_needs_a_key_to_pick_openai(am, monkeypatch):
    from config import cfg
    monkeypatch.setattr(cfg, "_data", {**cfg._data, "tts_provider": "auto",
                                       "openai_api_key": ""})
    assert am._tts_backend() == "gtts"
    monkeypatch.setattr(cfg, "_data", {**cfg._data, "tts_provider": "auto",
                                       "openai_api_key": "sk-test"})
    assert am._tts_backend() == "openai"


# ─── Splitting a single long sentence ─────────────────────────────────────────

def test_one_long_sentence_is_broken_at_its_middle_comma():
    """The common case: the vision model returns ONE 100-char sentence. Left
    whole it is one long synthesis the user waits through in silence."""
    text = ("Di depan hanya tampak bidang kuning kecokelatan polos, "
            "tanpa orang atau objek yang dapat dikenali.")
    assert split_sentences(text) == [
        "Di depan hanya tampak bidang kuning kecokelatan polos,",
        "tanpa orang atau objek yang dapat dikenali."]


def test_short_sentences_and_lists_are_left_alone():
    # Below the length threshold: splitting would cost a round-trip and buy
    # nothing, and "Ada meja," alone is not worth its own render.
    assert split_sentences("Ada meja, kursi, dan lampu.") == ["Ada meja, kursi, dan lampu."]
    assert split_sentences("Halo.") == ["Halo."]


def test_comma_split_is_off_when_streaming_is_disabled():
    text = ("Di depan hanya tampak bidang kuning kecokelatan polos, "
            "tanpa orang atau objek yang dapat dikenali.")
    assert split_sentences(text, max_chunks=1) == [text]


def test_a_long_sentence_with_no_comma_breaks_before_a_clause_opener():
    """The case comma-splitting misses, and the one that measured slowest:
    a 108-char single clause-less sentence rendered as one 5.5 s gTTS call."""
    text = ("Di depan hanya terlihat bidang berwarna kuning kecokelatan polos "
            "tanpa objek atau orang yang dapat dikenali.")
    assert split_sentences(text) == [
        "Di depan hanya terlihat bidang berwarna kuning kecokelatan polos",
        "tanpa objek atau orang yang dapat dikenali."]


def test_a_comma_beats_a_clause_opener_when_both_are_available():
    text = ("Di depan hanya tampak bidang kuning kecokelatan polos, "
            "tanpa orang atau objek yang dapat dikenali.")
    assert split_sentences(text)[0].endswith(","), split_sentences(text)


def test_a_sentence_with_no_natural_pause_is_left_whole():
    """Better one slower render than a break mid-clause: each chunk carries its
    own intonation contour, so an unnatural seam is audible."""
    text = ("Sebuah motor merah melaju cepat dari arah kanan menuju "
            "persimpangan jalan di depan.")
    assert split_sentences(text) == [text]


def test_a_clause_opener_too_near_an_edge_is_not_used():
    # "dan" sits 8 chars in — splitting there strands a fragment not worth its
    # own round-trip, and the tail would be almost the whole sentence anyway.
    text = "Ada meja dan beberapa kursi kayu yang tersusun rapi di ruangan itu."
    assert split_sentences(text) == [text]


# ─── Boot-time pre-warm ───────────────────────────────────────────────────────

def test_warm_speech_stack_pays_the_import_cost_up_front(am, monkeypatch):
    """`import gtts` is 6 s on this board and _synthesize imports inside the
    function, so without this the first describe after every boot ate it."""
    warmed = []
    monkeypatch.setattr(am, "_tts_synthesize",
                        lambda text: warmed.append(text) or "/tmp/w.wav")

    am.warm_speech_stack()

    assert _wait(lambda: warmed), "nothing was pre-warmed"
    assert warmed == [am_mod._WARM_PHRASE]


def test_warm_speech_stack_retries_while_wifi_is_still_associating(am, monkeypatch):
    """At boot the radio may not have an address yet; one failed render must not
    leave the device cold until the user's first press."""
    monkeypatch.setattr(am_mod, "_WARM_STACK_RETRY_GAP_S", 0.01)
    attempts = []

    def _flaky(text):
        attempts.append(text)
        return "/tmp/w.wav" if len(attempts) >= 3 else None

    monkeypatch.setattr(am, "_tts_synthesize", _flaky)

    am.warm_speech_stack()

    assert _wait(lambda: len(attempts) >= 3), attempts
    time.sleep(0.1)
    assert len(attempts) == 3, "kept retrying after a successful warm"


def test_warm_speech_stack_never_renders_on_the_paid_backend(am, monkeypatch):
    """A render per boot would be a real charge; only DNS+TLS is pre-paid there."""
    from config import cfg
    monkeypatch.setattr(cfg, "_data", {**cfg._data, "tts_provider": "openai",
                                       "openai_api_key": "sk-test"})

    def _no_render(text):
        raise AssertionError("pre-warm billed a synthesis on the openai backend")
    monkeypatch.setattr(am, "_tts_synthesize", _no_render)
    monkeypatch.setattr("socket.getaddrinfo",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))

    am.warm_speech_stack()
    time.sleep(0.2)

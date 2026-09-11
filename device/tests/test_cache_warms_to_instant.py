"""Verify the product claim: the per-word caching mode gets more "instant" the
more it's used.

Mechanism under test (all through the REAL decision code — speak_scene +
plan_utterance + WordCache): a scene sentence whose words aren't all cached is
spoken as one whole-sentence synth (slow, network); after its words are warmed
into the cache, the SAME vocabulary renders by concatenating cached word-audio —
zero network, instant. Because Indonesian scene sentences reuse a small
recurring vocabulary, repeated use drives the hit-rate toward 100% and the
per-utterance synthesis work toward 0.

Synthesis is faked (no network/hardware); warming is made synchronous so the
convergence is deterministic.
"""

import pytest

import core.audio_manager as am_mod
from utils.word_cache import WordCache, plan_utterance, tokenize


class _NullLogger:
    def __getattr__(self, _name):
        return lambda *a, **k: None


@pytest.fixture
def am(tmp_path, monkeypatch):
    """Real AudioManager with the word cache redirected to a temp dir, caching
    on, trim/gap neutralised (smoothing is covered elsewhere)."""
    from config import cfg
    monkeypatch.setattr(cfg, "_data", {**cfg._data,
                                       "word_cache_dir": str(tmp_path),
                                       "word_cache_enabled": True,
                                       "word_cache_trim_enabled": False,
                                       "word_cache_gap_ms": 0,
                                       "tts_enabled": True,
                                       "audio_mode": "both"})
    mgr = am_mod.AudioManager(orchestrator=None, logger=_NullLogger())
    yield mgr
    mgr.stop()


@pytest.fixture
def record(am, monkeypatch):
    """Capture which render path speak_scene chooses, and warm words
    synchronously (network-free) so 'next use' sees a warmed cache."""
    events = []
    monkeypatch.setattr(am, "queue_pcm_bytes",
                        lambda pcm, text, **k: events.append("instant"))
    monkeypatch.setattr(am, "_queue_scene_synth",
                        lambda text, scene_id=None: events.append("synth"))

    def warm_now(words):
        for w in words:
            am._word_cache.store(w, (w.encode() or b"_") * 8)
    monkeypatch.setattr(am, "_warm_words_async", warm_now)
    return events


def test_repeated_sentence_goes_from_synth_to_instant(am, record):
    sentence = "Kasur di kiri, pintu di depan, dan meja di kanan."

    # First time: nothing cached → whole-sentence synth (the slow path).
    am.speak_scene(sentence)
    assert record == ["synth"]

    # Its words are now warmed → the SAME sentence renders instant (zero synth).
    am.speak_scene(sentence)
    assert record == ["synth", "instant"]

    # Stays instant on every further use.
    am.speak_scene(sentence)
    assert record == ["synth", "instant", "instant"]


# A realistic "sedang" corpus: short room descriptions that reuse a small core
# vocabulary (kasur, pintu, di, kiri, depan, kanan, dan, …).
SEDANG_CORPUS = [
    "Kasur di kiri, pintu di depan, dan meja di kanan.",
    "Pakaian di kiri, kasur di depan, televisi di kanan.",
    "Selimut di kiri, pintu di depan, dan baju di kanan.",
    "Ada kasur di kiri, pintu di depan, dan stopkontak di kanan.",
    "Kasur di kiri, pakaian di kanan, dan dinding di depan.",
]


def test_recurring_corpus_converges_to_all_instant(am, monkeypatch):
    # Warm at most `cap` words per miss — exactly like _warm_words_async — so the
    # convergence reflects the real bounded warming, not an idealised one.
    cap = 8
    seq = []
    monkeypatch.setattr(am, "queue_pcm_bytes",
                        lambda pcm, text, **k: seq.append("instant"))
    monkeypatch.setattr(am, "_queue_scene_synth",
                        lambda text, scene_id=None: seq.append("synth"))

    def warm_capped(words):
        for w in list(words)[:cap]:
            am._word_cache.store(w, (w.encode() or b"_") * 8)
    monkeypatch.setattr(am, "_warm_words_async", warm_capped)

    # Run the corpus repeatedly; record how many sentences render instant per pass.
    instant_per_pass = []
    for _ in range(6):
        seq.clear()
        for s in SEDANG_CORPUS:
            am.speak_scene(s)
        instant_per_pass.append(seq.count("instant"))

    # The claim, made measurable:
    #  - cold start: not everything is instant yet
    assert instant_per_pass[0] < len(SEDANG_CORPUS)
    #  - more use never makes it worse (monotonic non-decreasing)
    assert instant_per_pass == sorted(instant_per_pass)
    #  - it converges to EVERY sentence instant (zero synthesis = zero network)
    assert instant_per_pass[-1] == len(SEDANG_CORPUS)


def test_never_repeating_vocabulary_never_gets_instant(am, monkeypatch):
    # Honesty check: "instant" comes from vocabulary REUSE. If every description
    # introduces all-new words, warming can't help and it stays on the slow
    # whole-sentence synth path — the claim is conditional, not magic.
    seq = []
    monkeypatch.setattr(am, "queue_pcm_bytes",
                        lambda pcm, text, **k: seq.append("instant"))
    monkeypatch.setattr(am, "_queue_scene_synth",
                        lambda text, scene_id=None: seq.append("synth"))

    def warm_now(words):
        for w in words:
            am._word_cache.store(w, (w.encode() or b"_") * 8)
    monkeypatch.setattr(am, "_warm_words_async", warm_now)

    for i in range(8):
        am.speak_scene(f"alphaword{i} betaword{i} gammaword{i} deltaword{i}")

    assert seq == ["synth"] * 8   # never instant — no reuse, no win

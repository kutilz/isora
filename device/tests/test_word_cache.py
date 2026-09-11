"""Per-word TTS cache: render a sentence from cached word-audio when possible
(zero network -> instant), else speak the whole sentence so a word is never
dropped ("ompong"). These tests pin the pure decision logic; synthesis and
playback are injected so they run with no network or hardware.
"""

import os
import struct

from utils.word_cache import (
    tokenize, plan_utterance, concat_pcm, WordCache,
    trim_silence, assemble_words,
)


def s16(*vals):
    """Build little-endian s16 PCM from sample values."""
    return b"".join(struct.pack("<h", v) for v in vals)


def test_count_reports_only_nonempty_cached_words(tmp_path):
    cache = WordCache(str(tmp_path))
    assert cache.count() == 0
    cache.store("kasur", s16(1, 2, 3))
    cache.store("pintu", s16(4, 5, 6))
    assert cache.count() == 2
    # store() refuses empty audio, so a silent word never inflates the count
    assert cache.store("kosong", b"") is False
    assert cache.count() == 2


def test_tokenize_normalizes_case_and_strips_punctuation():
    # "Depan," and "depan" must collapse to the same cache key, and the
    # sentence-final "Anda!" must match a plain "anda" -> higher hit rate.
    assert tokenize("Di depan, Anda!") == ["di", "depan", "anda"]


def test_all_words_cached_renders_from_concatenation_no_network():
    cache = {"di": "di.pcm", "depan": "depan.pcm", "anda": "anda.pcm"}
    plan = plan_utterance("Di depan Anda", cache.get)
    assert plan.mode == "concat"
    assert plan.word_paths == ["di.pcm", "depan.pcm", "anda.pcm"]
    assert plan.missing == []


def test_one_missing_word_speaks_whole_sentence_and_lists_warmups():
    # "anda" not cached -> NEVER speak a partial sentence; say the whole thing
    # via gTTS, and report the missing word so it can be warmed for next time.
    cache = {"di": "di.pcm", "depan": "depan.pcm"}
    plan = plan_utterance("Di depan Anda", cache.get)
    assert plan.mode == "synth_sentence"
    assert plan.word_paths == []
    assert plan.missing == ["anda"]


def test_missing_words_deduped_preserving_first_seen_order():
    plan = plan_utterance("biru dan biru tua", lambda w: None)
    assert plan.missing == ["biru", "dan", "tua"]


def test_concat_joins_word_audio_in_order():
    blobs = {"a.pcm": b"AAAA", "b.pcm": b"BBBB"}
    assert concat_pcm(["a.pcm", "b.pcm"], blobs.get) == b"AAAABBBB"


def test_concat_inserts_silence_gap_between_words():
    blobs = {"a.pcm": b"AA", "b.pcm": b"BB"}
    assert concat_pcm(["a.pcm", "b.pcm"], blobs.get, gap_bytes=b"__") == b"AA__BB"


def test_concat_aborts_if_any_word_audio_missing():
    # If a cached word's audio can't be read, refuse to build a gappy clip —
    # return None so the caller falls back to whole-sentence synthesis.
    blobs = {"a.pcm": b"AAAA"}
    assert concat_pcm(["a.pcm", "b.pcm"], blobs.get) is None


def test_wordcache_store_then_lookup_roundtrips(tmp_path):
    wc = WordCache(str(tmp_path))
    assert wc.lookup("biru") is None          # cold
    assert wc.store("biru", b"\x01\x02\x03\x04")
    p = wc.lookup("biru")
    assert p and os.path.exists(p)
    # case/punctuation normalised the same way tokenize does -> same entry
    assert wc.lookup("Biru,") == p


def test_wordcache_zero_byte_entry_is_not_a_hit(tmp_path):
    # A silent (empty) word would be ompong; it must not count as cached.
    wc = WordCache(str(tmp_path))
    assert not wc.store("kosong", b"")
    assert wc.lookup("kosong") is None


# ── silence trimming + assembly (smooth out per-word concatenation) ──────────

def test_trim_drops_leading_and_trailing_silence():
    pcm = s16(0, 0, 0, 5000, -6000, 0, 0, 0)
    assert trim_silence(pcm, threshold=1000, margin_samples=0) == s16(5000, -6000)


def test_trim_keeps_a_margin_around_the_signal():
    pcm = s16(0, 0, 5000, 0, 0)
    assert trim_silence(pcm, threshold=1000, margin_samples=1) == s16(0, 5000, 0)


def test_trim_all_silence_returns_input_unchanged():
    pcm = s16(0, 0, 0)
    assert trim_silence(pcm, threshold=1000, margin_samples=0) == pcm


def test_assemble_positive_gap_inserts_silence_between_words():
    out = assemble_words([s16(100, 200), s16(300)], gap_samples=1)
    assert out == s16(100, 200, 0, 300)


def test_assemble_negative_gap_overlaps_by_dropping_seam_samples():
    # gap=-2 -> remove 2 samples at the seam, split across the two words.
    out = assemble_words([s16(1, 2, 3, 4), s16(5, 6, 7, 8)], gap_samples=-2)
    assert out == s16(1, 2, 3, 6, 7, 8)


def test_assemble_trims_each_word_when_threshold_set():
    out = assemble_words([s16(0, 5000, 0), s16(0, 6000, 0)],
                         gap_samples=0, trim_threshold=1000, trim_margin_samples=0)
    assert out == s16(5000, 6000)

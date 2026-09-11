"""Integration: speak_scene() wiring through the real AudioManager.

Proves the zero-network path end to end — when every word of a sentence is
already in the word cache, speak_scene concatenates the cached word-audio and
hands it to playback as ready PCM (no synthesis, no network). Only the maix
hardware playback call is stubbed; the queue, loop thread, planner, concat and
WordCache are all real.
"""

import time

import pytest

import core.audio_manager as am_mod
from utils.word_cache import WordCache, tokenize


class _NullLogger:
    def __getattr__(self, _name):
        return lambda *a, **k: None


@pytest.fixture
def am(tmp_path, monkeypatch):
    # Redirect the word cache to a temp dir before construction (no host litter).
    # Trim off + zero gap so the HIT output is a deterministic plain concat
    # (smoothing is covered by the word_cache unit tests).
    from config import cfg
    monkeypatch.setattr(cfg, "_data", {**cfg._data,
                                       "word_cache_dir": str(tmp_path),
                                       "word_cache_trim_enabled": False,
                                       "word_cache_gap_ms": 0})
    mgr = am_mod.AudioManager(orchestrator=None, logger=_NullLogger())
    yield mgr
    mgr.stop()


def test_fully_cached_sentence_plays_concatenated_bytes_no_synth(am, monkeypatch):
    text = "Di depan Anda"

    # Warm every word with recognisable fake PCM.
    blobs = {w: (w.encode() * 4) for w in tokenize(text)}  # di/depan/anda
    for w, b in blobs.items():
        assert am._word_cache.store(w, b)

    # Stub playback + guarantee synthesis is NEVER called on this path.
    played = []
    monkeypatch.setattr(am, "_play_pcm_bytes", lambda data: played.append(bytes(data)) or True)

    def _no_synth(_text):
        raise AssertionError("speak_scene synthesized on a full cache hit")
    monkeypatch.setattr(am, "_tts_synthesize", _no_synth)

    am.speak_scene(text)

    # Loop thread picks up the queued PCM task and "plays" it.
    deadline = time.monotonic() + 3.0
    while not played and time.monotonic() < deadline:
        time.sleep(0.02)

    assert played, "no audio was played"
    # Bytes are the cached words concatenated in order (trim off, gap 0).
    expected = blobs["di"] + blobs["depan"] + blobs["anda"]
    assert played[0] == expected

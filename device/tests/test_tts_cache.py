"""Disk-cache correctness for the TTS renderers.

Two things here have burned us, both silent: a synthesis abandoned on timeout
left a half-written mp3 that the next lookup served as a cache hit (the
description played, then cut off mid-word), and the cache pruner counted files
rather than utterances, so a cache of ffmpeg-free OpenAI entries could grow past
its cap on a board with ~4 MB free.
"""

import os
import time

import utils.tts as tts


def test_a_timed_out_render_never_leaves_a_playable_partial(tmp_path, monkeypatch):
    out = str(tmp_path / "x.wav")

    class _SlowGTTS:
        def __init__(self, **kw):
            pass

        def save(self, path):
            with open(path, "wb") as f:      # a partial write, as .save() streams
                f.write(b"half an mp3")
            time.sleep(1.0)                  # …still going when we give up
            with open(path, "ab") as f:
                f.write(b"the rest")

    monkeypatch.setitem(__import__("sys").modules, "gtts",
                        type("m", (), {"gTTS": _SlowGTTS}))

    assert tts._synthesize("halo", out, "id", timeout_s=0.2) is None
    assert not os.path.exists(out), "abandoned render left a truncated cache hit"


def test_prune_counts_utterances_not_files(tmp_path):
    d = str(tmp_path)
    # 3 gTTS entries (wav+pcm each) and 3 OpenAI ones (a lone .o.pcm each).
    for i in range(3):
        for suffix in (".wav", ".pcm"):
            open(os.path.join(d, "g%d%s" % (i, suffix)), "wb").close()
        open(os.path.join(d, "o%d.o.pcm" % i), "wb").close()
        time.sleep(0.01)                     # distinct mtimes, oldest first

    tts._prune_cache(d, max_entries=4)

    stems = {f.split(".")[0] for f in os.listdir(d)}
    assert len(stems) == 4, sorted(os.listdir(d))
    # The two oldest utterances went, and a gTTS entry took its .pcm with it.
    assert "g0" not in stems and "o0" not in stems
    assert "o2" in stems and "g2" in stems
    assert sorted(os.listdir(d)).count("g2.pcm") == 1


def test_openai_cache_key_changes_with_the_voice(tmp_path, monkeypatch):
    calls = []

    def _fake_urlopen(req, timeout=0):
        calls.append(req.data)

        class _R:
            def read(self):
                return b"\x00\x01" * 100

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        return _R()

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    a = tts.get_or_synthesize_pcm("halo", api_key="k", cache_dir=str(tmp_path),
                                  voice="alloy")
    b = tts.get_or_synthesize_pcm("halo", api_key="k", cache_dir=str(tmp_path),
                                  voice="nova")
    again = tts.get_or_synthesize_pcm("halo", api_key="k", cache_dir=str(tmp_path),
                                      voice="alloy")
    assert a and b and a != b, "two voices shared one cache entry"
    assert again == a and len(calls) == 2, "cache miss on a repeat"


def test_openai_render_is_upsampled_to_the_rate_the_codec_plays():
    # OpenAI answers at 24 kHz; the MaixCAM codec only opens at 48 kHz, so an
    # un-resampled clip would play at half speed.
    raw = b"\x01\x00\x02\x00" * 500                      # 1000 samples @ 24 kHz
    out = tts._upsample_2x(raw)
    assert abs(len(out) - 2 * len(raw)) <= 2, len(out)   # ratecv drops a tail sample


def test_upsample_falls_back_when_audioop_is_gone(monkeypatch):
    """audioop is removed in Python 3.13 — the device must still speak."""
    import builtins
    real_import = builtins.__import__

    def _no_audioop(name, *a, **k):
        if name == "audioop":
            raise ImportError("removed in 3.13")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _no_audioop)
    assert tts._upsample_2x(b"\x01\x00\x02\x00") == b"\x01\x00\x01\x00\x02\x00\x02\x00"

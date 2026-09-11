"""Playback must never hand MaixPy's Player.play() more than it accepts.

Regression guard for a silent-truncation bug: Player.play() keeps only the
first 512 KiB of a single call, drops the rest and returns ERR_RUNTIME, which
the caller ignored. At 48 kHz s16le mono that is 5.46 s, so chimes and
greetings were fine while every scene description longer than ~5.4 s was cut
in half mid-sentence — with nothing in the app log to show for it.

The failure is invisible from the outside (no exception, no error line), so it
is tested at the only place it shows: the sizes handed to the driver, and
whether the bytes that arrive reassemble into the clip we meant to play.
"""

import sys
import threading
import types

import pytest

import core.audio_manager as am_mod


class _NullLogger:
    def __getattr__(self, _name):
        return lambda *a, **k: None


class _FakeClock:
    """Virtual time: sleep() advances the clock instead of blocking.

    _play_pcm_bytes paces its writes against the playback rate, so on a real
    clock these tests would take as long as the audio they play.
    """

    def __init__(self):
        self.t = 0.0

    def monotonic(self):
        return self.t

    def sleep(self, s):
        self.t += max(0.0, s)


class _FakePlayer:
    """Records every play() payload; mimics the 512 KiB per-call ceiling."""

    LIMIT = am_mod._PLAY_DRIVER_LIMIT_BYTES

    def __init__(self, sink):
        self._sink = sink

    def volume(self, _v=-1):
        raise RuntimeError("Not implemented: Not support now")   # as on 4.5.1

    def play(self, data):
        self._sink.append(bytes(data))
        # The driver keeps only what fits and reports the shortfall.
        return 0 if len(data) <= self.LIMIT else 13


@pytest.fixture
def play_calls(monkeypatch):
    """Install a fake `maix.audio` and return the list of play() payloads."""
    calls = []
    audio_mod = types.ModuleType("maix.audio")
    audio_mod.Player = lambda: _FakePlayer(calls)
    maix_mod = types.ModuleType("maix")
    maix_mod.audio = audio_mod
    monkeypatch.setitem(sys.modules, "maix", maix_mod)
    monkeypatch.setitem(sys.modules, "maix.audio", audio_mod)
    monkeypatch.setattr(am_mod, "time", _FakeClock())
    return calls


def _player_stub():
    """Minimal self for _play_pcm_bytes — no queue, no thread."""
    stub = types.SimpleNamespace()
    stub._interrupt = threading.Event()
    stub._stop = threading.Event()
    stub.logger = _NullLogger()
    return stub


def _pcm(seconds):
    # Content varies per byte so a dropped/reordered slice cannot pass unnoticed.
    n = int(am_mod._PCM_BYTES_S * seconds)
    return bytes((i * 7 + 11) & 0xFF for i in range(n))


def _as_played(data):
    """What the driver should receive for `data`.

    _FakePlayer.volume() raises, exactly as MaixPy 4.5.1 does, so playback now
    applies the level in software instead of letting audio_volume stay a number
    the speaker ignores. These tests are about truncation and ordering, so they
    compare against the scaled bytes rather than the raw ones.
    """
    from config import cfg
    return am_mod.apply_software_gain(data, cfg.AUDIO_VOLUME)


def test_long_clip_is_split_and_every_byte_reaches_the_driver(play_calls):
    """A 12 s clip is >2x the driver ceiling: it must arrive whole, in pieces."""
    data = _pcm(12.0)
    assert len(data) > am_mod._PLAY_DRIVER_LIMIT_BYTES     # the bug's precondition

    ok = am_mod.AudioManager._play_pcm_bytes(_player_stub(), data)

    assert ok is True
    assert len(play_calls) > 1, "oversized clip was pushed in a single play()"
    for i, payload in enumerate(play_calls):
        assert len(payload) <= am_mod._PLAY_DRIVER_LIMIT_BYTES, (
            "chunk %d is %d bytes — the driver would silently drop the tail"
            % (i, len(payload)))
    assert b"".join(play_calls) == _as_played(data), (
        "audio was truncated or reordered")


def test_short_clip_still_goes_out_in_one_call(play_calls):
    """Cues under the chunk size must not be needlessly fragmented."""
    data = _pcm(am_mod._PLAY_CHUNK_S / 2)

    assert am_mod.AudioManager._play_pcm_bytes(_player_stub(), data) is True
    assert len(play_calls) == 1
    assert play_calls[0] == _as_played(data)


def test_exactly_one_chunk_is_not_split(play_calls):
    data = _pcm(am_mod._PLAY_CHUNK_S)

    am_mod.AudioManager._play_pcm_bytes(_player_stub(), data)
    assert len(play_calls) == 1


def test_interrupt_stops_feeding_the_rest_of_a_long_clip(play_calls):
    """A higher-priority cue must not wait out a 30 s description."""
    stub = _player_stub()
    stub._interrupt.set()
    data = _pcm(30.0)

    assert am_mod.AudioManager._play_pcm_bytes(stub, data) is True
    # First chunk may already be in flight; the remaining ~15 must not be.
    assert len(play_calls) <= 1
    assert sum(len(p) for p in play_calls) < len(data)


def test_volume_not_supported_does_not_lose_the_clip(play_calls):
    """Player.volume() raises on MaixPy 4.5.1 — playback must continue anyway."""
    data = _pcm(1.0)

    assert am_mod.AudioManager._play_pcm_bytes(_player_stub(), data) is True
    assert b"".join(play_calls) == _as_played(data)
    assert len(b"".join(play_calls)) == len(data), "no samples were lost"


def _loud_pcm(nsamples=100):
    """s16le samples at a fixed, clearly non-zero amplitude."""
    return bytes([0x00, 0x40] * nsamples)


def test_volume_is_applied_in_software_when_the_driver_refuses():
    """The whole point: a level the firmware cannot set must still be audible.

    Player.volume() raising used to be swallowed, so every clip played at the
    codec default. audio_volume became a number four UIs displayed and the
    speaker ignored, and the volume chord did nothing a blind user could hear.
    """
    import audioop
    raw = _loud_pcm()

    assert am_mod.apply_software_gain(raw, 100) == raw, "100% must not touch samples"

    quiet = am_mod.apply_software_gain(raw, 50)
    assert quiet != raw, "50% must actually scale the samples"
    assert len(quiet) == len(raw), "scaling must not change the clip length"
    assert audioop.max(quiet, 2) < audioop.max(raw, 2)

    floor = am_mod.apply_software_gain(raw, 20)
    assert audioop.max(floor, 2) < audioop.max(quiet, 2), "steps must be ordered"
    assert audioop.max(floor, 2) > 0, "the floor must stay audible, not silent"


def test_hardware_volume_is_preferred_when_the_firmware_supports_it():
    """On a build with a working Player.volume() the samples stay untouched."""

    class _Supported:
        def __init__(self):
            self.asked = None

        def volume(self, v):
            self.asked = v

    p = _Supported()
    data = _loud_pcm()
    out = am_mod.set_player_volume(p, 30, data)
    assert p.asked == 30
    assert out is data, "no software gain when the driver did the work"


def test_empty_pcm_is_rejected(play_calls):
    assert am_mod.AudioManager._play_pcm_bytes(_player_stub(), b"") is False
    assert play_calls == []

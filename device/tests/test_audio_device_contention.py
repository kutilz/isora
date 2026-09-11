"""Two playback paths share one codec — neither may lose its clip to the other.

The MaixCAM codec accepts exactly one open `maix.audio.Player`. Two independent
paths open one: `play_wav_blocking` (the boot cues, which run before an
AudioManager exists) and `AudioManager._play_pcm_bytes` (the queue worker).
At boot they overlap — the "menghubungkan ke wifi" cue is still sounding when
the ready chime is queued — and the loser got

    RuntimeError: : Runtime error: failed to open PCM

which the caller swallowed into a text-only fallback. The observable damage:
on a device for blind users, "I-Sora siap digunakan" was never spoken.

Tested through the two public playback entry points against a codec fake that
enforces the real one-at-a-time rule, so the assertion is "the clip was heard",
not "a lock exists".
"""

import os
import sys
import threading
import types

import pytest

import core.audio_manager as am_mod


class _NullLogger:
    def __getattr__(self, _name):
        return lambda *a, **k: None


class _Codec:
    """Fake `maix.audio` codec: one Player at a time, released when dropped.

    Release is tied to object destruction because that is what frees the codec
    on the device too (Player has no stop() on MaixPy 4.5.1 — the destructor is
    the hard stop, see _play_pcm_bytes).
    """

    def __init__(self):
        self._mutex = threading.Lock()
        self._open = 0
        self.sink = []                          # payloads the codec received
        self.refused = 0                        # opens rejected as busy
        self.first_play_started = threading.Event()
        self.hold = threading.Event()           # test-held: pins clip 1 open
        self._held_once = False

    # Stands in for maix.audio.Player
    def Player(self):
        with self._mutex:
            if self._open:
                self.refused += 1
                raise RuntimeError(": Runtime error: failed to open PCM")
            self._open += 1
        return _FakePlayer(self)

    def _release(self):
        with self._mutex:
            self._open -= 1


class _FakePlayer:
    def __init__(self, codec):
        self._codec = codec

    def volume(self, _v=-1):
        raise RuntimeError("Not implemented: Not support now")   # as on 4.5.1

    def play(self, data):
        codec = self._codec
        codec.sink.append(bytes(data))
        if not codec._held_once:
            codec._held_once = True
            codec.first_play_started.set()
            codec.hold.wait(timeout=5.0)        # keep the codec occupied
        return 0

    def __del__(self):
        self._codec._release()


@pytest.fixture
def codec(monkeypatch):
    c = _Codec()
    audio_mod = types.ModuleType("maix.audio")
    audio_mod.Player = c.Player
    maix_mod = types.ModuleType("maix")
    maix_mod.audio = audio_mod
    monkeypatch.setitem(sys.modules, "maix", maix_mod)
    monkeypatch.setitem(sys.modules, "maix.audio", audio_mod)
    return c


def _pcm_bytes(seconds):
    n = int(am_mod._PCM_BYTES_S * seconds)
    return bytes((i * 7 + 11) & 0xFF for i in range(n))


def _as_played(data):
    """The bytes the codec should receive for `data`.

    _FakePlayer.volume() raises exactly as MaixPy 4.5.1 does, so playback now
    applies audio_volume in software rather than leaving it a number the
    speaker never hears. These tests are about clips reaching the codec at all,
    so they match on the scaled form.
    """
    from config import cfg
    return am_mod.apply_software_gain(data, cfg.AUDIO_VOLUME)


def _cue_on_disk(tmp_path, name, seconds):
    """A WAV with its .pcm already cached, so no ffmpeg is needed."""
    wav = tmp_path / name
    wav.write_bytes(b"RIFF....WAVEfmt ")
    pcm = tmp_path / (os.path.splitext(name)[0] + ".pcm")
    data = _pcm_bytes(seconds)
    pcm.write_bytes(data)
    return data


def _worker_stub():
    stub = types.SimpleNamespace()
    stub._interrupt = threading.Event()
    stub._stop = threading.Event()
    stub.logger = _NullLogger()
    return stub


def test_queued_cue_is_not_lost_while_a_boot_cue_is_playing(codec, tmp_path):
    """The ready chime must wait out the boot cue, not vanish into text."""
    boot_pcm = _cue_on_disk(tmp_path, "menghubungkan_ke_wifi.wav", 0.02)
    ready_pcm = _pcm_bytes(0.02)

    boot_ok = []
    threading.Thread(
        target=lambda: boot_ok.append(
            am_mod.play_wav_blocking("menghubungkan_ke_wifi.wav",
                                     audio_dir=str(tmp_path), volume=80)),
        daemon=True,
    ).start()
    assert codec.first_play_started.wait(timeout=5.0), "boot cue never started"

    ready_ok = []
    entered = threading.Event()

    def _queued():
        entered.set()
        ready_ok.append(
            am_mod.AudioManager._play_pcm_bytes(_worker_stub(), ready_pcm))

    t = threading.Thread(target=_queued, daemon=True)
    t.start()
    assert entered.wait(timeout=5.0)
    # Give the queued cue time to reach the codec while the boot cue holds it.
    threading.Event().wait(0.2)

    codec.hold.set()
    t.join(timeout=10.0)
    assert not t.is_alive(), "queued cue never finished"

    assert codec.refused == 0, (
        "the queued cue was refused the codec and fell back to text — "
        "the device stayed silent about being ready")
    assert ready_ok == [True]
    assert _as_played(ready_pcm) in codec.sink, "ready chime never reached the codec"
    assert _as_played(boot_pcm) in codec.sink, "boot cue was clobbered"


def test_a_wedged_holder_does_not_mute_the_queue_forever(codec, tmp_path,
                                                         monkeypatch):
    """Serialising playback must not trade one silence for a worse one.

    If the clip holding the codec never finishes, waiting on it forever would
    mute every obstacle alert from then on — strictly worse than the bug this
    gate fixes. The wait is bounded, and the queue recovers once the codec is
    free again.
    """
    monkeypatch.setattr(am_mod, "_DEVICE_WAIT_S", 0.2)
    _cue_on_disk(tmp_path, "wedged.wav", 0.02)

    holder = threading.Thread(
        target=lambda: am_mod.play_wav_blocking(
            "wedged.wav", audio_dir=str(tmp_path), volume=80),
        daemon=True,
    )
    holder.start()
    assert codec.first_play_started.wait(timeout=5.0)

    done = threading.Event()
    threading.Thread(
        target=lambda: (am_mod.AudioManager._play_pcm_bytes(
            _worker_stub(), _pcm_bytes(0.02)), done.set()),
        daemon=True,
    ).start()
    assert done.wait(timeout=3.0), (
        "a queued alert hung behind a wedged clip — the device would go "
        "permanently silent")

    # Codec freed: the next alert must be audible again.
    codec.hold.set()
    holder.join(timeout=5.0)
    recovered = _pcm_bytes(0.03)
    assert am_mod.AudioManager._play_pcm_bytes(_worker_stub(), recovered) is True
    assert _as_played(recovered) in codec.sink

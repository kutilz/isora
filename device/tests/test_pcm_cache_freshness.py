"""The WAV→PCM cache must survive this device's clock, not just a replaced WAV.

Every cue plays from a .pcm built next to its .wav by ffmpeg. Two ways that
cache goes wrong, and both are silent:

  - it hits when it should not — a re-recorded cue or a brand swap keeps playing
    the PREVIOUS sound forever, because the .pcm sibling is still there;
  - it misses when it should not — every queue_cue re-runs ffmpeg before the
    clip is audible, which on the CRITICAL "orang di depan" obstacle alert is
    the difference between a warning and a collision.

The second one is what an mtime ORDERING test does here. The device boots with
the wall clock at the epoch and NTP jumps it forward at an unpredictable point
during boot, while every WAV arrives over SSH carrying a present-day mtime — so
a .pcm rebuilt pre-NTP is stamped 1970 against a 2026 source and "is the .pcm
newer" is false forever. These tests pin the equality-against-source rule that
replaces it.
"""

import os
import subprocess

import pytest

from core.audio_manager import (
    _ensure_pcm_standalone,
    _pcm_is_fresh,
    _stamp_pcm,
)

# Far enough apart that no tolerance can confuse them: a WAV deployed while the
# device was NTP-synced, next to an artefact built while the clock read 1970.
_DEPLOYED = 1_780_000_000.0        # ~2026
_EPOCH_BOOT = 120.0                # two minutes after the epoch


def _wav_and_pcm(tmp_path):
    wav = tmp_path / "cue.wav"
    pcm = tmp_path / "cue.pcm"
    wav.write_bytes(b"RIFF....WAVE")
    pcm.write_bytes(b"\x00\x01" * 64)
    return str(wav), str(pcm)


def test_pcm_built_before_ntp_still_counts_as_fresh(tmp_path):
    """The regression: pre-NTP artefact, present-day source, cache must hit."""
    wav, pcm = _wav_and_pcm(tmp_path)
    os.utime(wav, (_DEPLOYED, _DEPLOYED))
    os.utime(pcm, (_EPOCH_BOOT, _EPOCH_BOOT))

    # As built on a device whose clock has not been corrected yet.
    assert not _pcm_is_fresh(wav, pcm)

    _stamp_pcm(wav, pcm)

    assert _pcm_is_fresh(wav, pcm)


def test_replaced_wav_invalidates_the_cache(tmp_path):
    """The property the mtime check was added for, unchanged by the fix."""
    wav, pcm = _wav_and_pcm(tmp_path)
    os.utime(wav, (_DEPLOYED, _DEPLOYED))
    _stamp_pcm(wav, pcm)
    assert _pcm_is_fresh(wav, pcm)

    # A new chime set lands next to last release's .pcm.
    os.utime(wav, (_DEPLOYED + 86_400, _DEPLOYED + 86_400))

    assert not _pcm_is_fresh(wav, pcm)


def test_wav_older_than_pcm_is_also_stale(tmp_path):
    """A rollback to a previous audio pack moves the source mtime BACKWARDS.

    Under an ordering test that .pcm stays 'fresh' and the device keeps playing
    the newer pack it was just rolled back from.
    """
    wav, pcm = _wav_and_pcm(tmp_path)
    os.utime(wav, (_DEPLOYED, _DEPLOYED))
    _stamp_pcm(wav, pcm)

    os.utime(wav, (_DEPLOYED - 86_400, _DEPLOYED - 86_400))

    assert not _pcm_is_fresh(wav, pcm)


def test_missing_pcm_is_not_fresh(tmp_path):
    wav, pcm = _wav_and_pcm(tmp_path)
    os.remove(pcm)

    assert not _pcm_is_fresh(wav, pcm)


def test_ensure_pcm_stamps_so_the_next_boot_is_a_cache_hit(tmp_path, monkeypatch):
    """End to end: two calls across a simulated clock jump, one ffmpeg run."""
    wav = tmp_path / "cue.wav"
    wav.write_bytes(b"RIFF....WAVE")
    os.utime(str(wav), (_DEPLOYED, _DEPLOYED))
    pcm = str(tmp_path / "cue.pcm")

    runs = []

    def fake_run(cmd, **kwargs):
        runs.append(cmd)
        # ffmpeg writes the artefact with the CURRENT clock, which pre-NTP is
        # the epoch — the exact condition that used to defeat the cache.
        with open(pcm, "wb") as f:
            f.write(b"\x00\x01" * 64)
        os.utime(pcm, (_EPOCH_BOOT, _EPOCH_BOOT))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert _ensure_pcm_standalone(str(wav)) == pcm
    assert _ensure_pcm_standalone(str(wav)) == pcm

    assert len(runs) == 1, "second call re-ran ffmpeg — the cache never hits"


def test_failed_conversion_is_not_stamped(tmp_path, monkeypatch):
    """A non-zero ffmpeg must not leave a stamped (i.e. trusted) artefact."""
    wav = tmp_path / "cue.wav"
    wav.write_bytes(b"RIFF....WAVE")
    os.utime(str(wav), (_DEPLOYED, _DEPLOYED))
    pcm = str(tmp_path / "cue.pcm")

    def fake_run(cmd, **kwargs):
        # ffmpeg's partial output on a truncated/corrupt source.
        with open(pcm, "wb") as f:
            f.write(b"\x00")
        os.utime(pcm, (_EPOCH_BOOT, _EPOCH_BOOT))
        return subprocess.CompletedProcess(cmd, 1)

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert _ensure_pcm_standalone(str(wav)) is None
    assert not _pcm_is_fresh(str(wav), pcm)


def test_stamp_never_raises_on_a_read_only_artefact(tmp_path):
    """Best-effort by contract: a failed stamp costs a rebuild, not a crash."""
    wav, _pcm = _wav_and_pcm(tmp_path)

    _stamp_pcm(wav, str(tmp_path / "does-not-exist.pcm"))

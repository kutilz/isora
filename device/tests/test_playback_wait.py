"""Playback hold time must not double-count a blocking player.

On this MaixPy build player.play() BLOCKS until the audio finishes, yet
_play_pcm then slept an *additional* full clip-duration deadline — so every
utterance was held ~2x its length, the surplus being dead silence (the
"diem paling lama" the user hears). residual_playback_wait_s() decides how
much MORE to wait after play() returns, given how long play() itself took.
"""

from core.audio_manager import residual_playback_wait_s, _PCM_BYTES_S


def test_blocking_player_adds_only_tail_pad():
    # 2s of audio, play() already blocked the full 2s -> nothing left but the pad
    nbytes = 2 * _PCM_BYTES_S
    assert residual_playback_wait_s(nbytes, play_call_elapsed_s=2.0) == 0.15


def test_nonblocking_player_waits_the_whole_clip():
    # play() returned instantly -> we must wait the clip out ourselves
    nbytes = 2 * _PCM_BYTES_S
    assert residual_playback_wait_s(nbytes, play_call_elapsed_s=0.0) == 2.15


def test_never_negative_when_play_overruns():
    nbytes = 2 * _PCM_BYTES_S
    assert residual_playback_wait_s(nbytes, play_call_elapsed_s=5.0) == 0.0

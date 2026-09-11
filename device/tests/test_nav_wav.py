"""
Tests for AudioManager.nav_wav_candidates — the offline-fallback resolution
order for a nav alert (Decision 4A: a missing file must never mean silence).

This is a pure staticmethod, so it's testable without the maix hardware layer
(maix is only imported inside playback methods).
"""

from core.audio_manager import AudioManager


def test_near_prefers_tier_specific_then_plain_then_generic():
    c = AudioManager.nav_wav_candidates("person", "center", "near")
    assert c == [
        "obj_person_center_near.wav",  # "...dekat" urgency phrase
        "obj_person_center.wav",       # plain phrase
        "objek_center.wav",            # generic "ada objek di depan"
    ]


def test_far_falls_back_to_plain_phrase():
    # No dedicated _far file is rendered; the plain phrase serves the far tier.
    c = AudioManager.nav_wav_candidates("chair", "left", "far")
    assert c[0] == "obj_chair_left_far.wav"
    assert "obj_chair_left.wav" in c       # plain fallback present
    assert "objek_left.wav" in c           # generic fallback present


def test_generic_fallback_is_always_last_resort_before_earcon():
    # The generic per-direction phrase is label-agnostic and is the final
    # speech option before the caller drops to the obstacle earcon.
    c = AudioManager.nav_wav_candidates("backpack", "kanan", "near")
    assert c[-1] == "objek_kanan.wav"

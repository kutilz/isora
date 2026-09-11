"""Chime synthesis: the properties that separate a chime from a fault beep.

The first chime set sounded like the device was malfunctioning, and the cause
was measurable rather than a matter of taste: constant-amplitude sine bursts
butt-joined end to end. These tests pin the three properties that fixed it, so a
future "let me just tweak the frequencies" edit cannot quietly regress the set
back into an alarm clock.

Kept in the device test suite (not tools/) because the WAVs they describe ship
to the device and are the only non-verbal feedback a blind user gets.
"""

import os
import sys
import wave

import numpy as np
import pytest

# tools/ is not a package; import generate_audio the way the script lives on disk.
_TOOLS = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "tools")
)
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import generate_audio  # noqa: E402

_AUDIO_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "audio")
)

CHIME_NAMES = sorted(generate_audio.CHIMES)


def _samples(name):
    """Rendered chime as float samples in -1..1."""
    return generate_audio._render_chime(
        generate_audio.CHIMES[name]
    ).astype(float) / 32768.0


# ─── Envelope: percussive, not flat ───────────────────────────────────────────

@pytest.mark.parametrize("name", CHIME_NAMES)
def test_envelope_is_percussive(name):
    """Crest factor (peak/RMS) is what the ear reads as "struck object".

    A flat sine burst sits near 1.41 — that shape IS the fault-beep sound. A
    decaying strike lands well above 3. This is the single property most
    responsible for the set no longer sounding like a malfunction.
    """
    d = _samples(name)
    crest = np.max(np.abs(d)) / np.sqrt((d ** 2).mean())
    assert crest > 3.0, f"{name}: crest {crest:.2f} — envelope is too flat"


@pytest.mark.parametrize("name", CHIME_NAMES)
def test_decays_to_near_silence_by_the_end(name):
    """The tail must die on its own, so playback never cuts a live tone."""
    d = _samples(name)
    tail = d[-int(len(d) * 0.05):]
    assert np.max(np.abs(tail)) < 0.02 * np.max(np.abs(d))


@pytest.mark.parametrize("name", CHIME_NAMES)
def test_starts_and_ends_at_zero(name):
    """A non-zero first/last sample is a click on every single playback."""
    d = _samples(name)
    assert d[0] == 0.0
    assert d[-1] == 0.0


# ─── No discontinuities ───────────────────────────────────────────────────────

@pytest.mark.parametrize("name", CHIME_NAMES)
def test_no_waveform_discontinuity(name):
    """Bound the sample-to-sample step at the steepest slope the content can
    legitimately produce (a full-scale sine at the highest partial present).

    A hard splice — the old set's butt-joined segments, or a note truncated
    mid-cycle — shows up here as a step far beyond that bound.
    """
    voice, notes = generate_audio.CHIMES[name]
    top_ratio = max(r for r, _g, _d in generate_audio._VOICES[voice])
    top_hz = max(f for f, _o, _r, _g in notes) * top_ratio
    peak = np.max(np.abs(_samples(name)))
    # Slope of A*sin(2*pi*f*t) per sample, with generous headroom for the sum
    # of partials landing in phase.
    bound = 2 * np.pi * top_hz * peak / generate_audio._CHIME_RATE * 2.5
    assert np.abs(np.diff(_samples(name))).max() < bound


# ─── Register: audible on the device's tiny speaker ───────────────────────────

@pytest.mark.parametrize("name", CHIME_NAMES)
def test_fundamentals_clear_the_speaker_rolloff(name):
    """Nothing below ~700 Hz.

    The driver in the device has no output down there; the previous error cue
    sat at 440 and 330 Hz and came out as a buzz rather than a tone. Anything
    the user must actually hear has to live above the rolloff.
    """
    _voice, notes = generate_audio.CHIMES[name]
    for freq, _onset, _ring, _gain in notes:
        assert freq >= 700.0, f"{name}: {freq} Hz is under the speaker rolloff"


@pytest.mark.parametrize("name", CHIME_NAMES)
def test_every_partial_stays_under_nyquist(name):
    """No partial may need the renderer's alias guard.

    _render_chime drops partials at or above Nyquist, which silently changes
    the timbre of whichever note tripped it. Keeping the whole set below the
    limit means what you hear is what the spec says.
    """
    voice, notes = generate_audio.CHIMES[name]
    nyquist = generate_audio._CHIME_RATE / 2
    for freq, _onset, _ring, _gain in notes:
        for ratio, _gain_p, _decay in generate_audio._VOICES[voice]:
            assert freq * ratio < nyquist, (
                f"{name}: partial {freq * ratio:.0f} Hz would alias"
            )


# ─── Level ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", CHIME_NAMES)
def test_normalized_with_headroom(name):
    """Every chime peaks at the same level, below full scale.

    Equal peaks stop one cue being startling next to another, and the headroom
    keeps the sum of partials from clipping into a rasp on the way out.
    """
    peak = np.max(np.abs(_samples(name)))
    assert peak == pytest.approx(generate_audio._CHIME_PEAK, abs=1e-3)
    assert peak < 0.8


# ─── Latency budget ───────────────────────────────────────────────────────────

def test_interactive_cues_stay_short():
    """A cue that precedes speech is pure added latency.

    press/mode/capture are acknowledgements — they play in front of the thing
    the user actually asked for, and the playback slot is held for the whole
    clip. Ring-out is free to be pretty; total length is not.
    """
    for name, budget_s in (("chime_press", 0.20),
                           ("chime_mode", 0.30),
                           ("chime_capture", 0.50)):
        dur = len(_samples(name)) / generate_audio._CHIME_RATE
        assert dur <= budget_s, f"{name}: {dur:.3f}s exceeds {budget_s}s"


# ─── Shipped artefacts match the generator ────────────────────────────────────

@pytest.mark.parametrize("name", CHIME_NAMES)
def test_shipped_wav_matches_the_generator(name):
    """audio/*.wav is a build artefact of CHIMES.

    Editing the spec without re-running `generate_audio.py --chimes` would ship
    the old sound while the code claims the new one — and the device caches a
    .pcm off the WAV, so that drift outlives several deploys.
    """
    path = os.path.join(_AUDIO_DIR, f"{name}.wav")
    if not os.path.exists(path):
        # audio/*.wav is gitignored — a fresh clone has no artefacts to check
        # until someone runs the generator. Nothing to drift from yet.
        pytest.skip("audio/ not generated here — run generate_audio.py --chimes")
    with wave.open(path) as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() == generate_audio._CHIME_RATE
        shipped = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    expected = generate_audio._render_chime(generate_audio.CHIMES[name])
    assert np.array_equal(shipped, expected), (
        f"{name}.wav is stale — re-run: python tools/generate_audio.py --chimes"
    )

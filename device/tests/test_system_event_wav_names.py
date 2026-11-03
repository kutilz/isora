"""
The pairing replies must resolve to pre-generated WAVs, not to gTTS.

`OnboardingAnnouncer.PAIR_REPLIES` answers a button press with `am.queue(text)`,
which looks the audio up **by its text**: `_find_wav` normalizes the sentence
(lowercase, spaces/hyphens to `_`, punctuation dropped) and tries `<safe>.wav`
then `system_<safe>.wav`. So each reply needs a `SYSTEM_EVENTS` entry whose key
*is* that normalized name, or `tools/generate_audio.py` writes a file nothing
ever looks for and the line silently falls back to gTTS.

That fallback needs a network — at exactly the moment one of these replies
("Belum ada internet…") exists to cover. It also looks perfectly fine in any
test environment that has internet, which is why this is a test.

Note the rule is specific to text-played cues. Entries like `mode_explorer` are
played via `queue_system(event)`, which passes `wav_name=f"{event}.wav"`
explicitly, so their keys are filenames and need not match their sentence.
"""

import importlib.util
import os
import sys

import pytest

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_GEN_AUDIO = os.path.join(_REPO_ROOT, "tools", "generate_audio.py")

pytestmark = pytest.mark.skipif(
    not os.path.exists(_GEN_AUDIO), reason="tools/generate_audio.py absent"
)


def _system_events():
    """Import tools/generate_audio.py by path — `tools/` is not a package."""
    spec = importlib.util.spec_from_file_location("isora_generate_audio", _GEN_AUDIO)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.SYSTEM_EVENTS


def _safe_name(text):
    """A local copy of the normalization in AudioManager._find_wav."""
    safe = text.lower().strip()
    safe = safe.replace(" ", "_").replace("-", "_").replace(",", "")
    return "".join(c for c in safe if c.isalnum() or c == "_")


def test_every_pairing_reply_has_a_pre_generated_wav_entry():
    from core.onboarding import OnboardingAnnouncer

    events = _system_events()
    missing = {}
    for reason, text in OnboardingAnnouncer.PAIR_REPLIES.items():
        key = _safe_name(text)
        if events.get(key) != text:
            missing[reason] = (key, text)

    assert not missing, (
        "pairing replies with no matching SYSTEM_EVENTS entry (they would fall "
        "back to gTTS, which needs the network they may be reporting as down): "
        + "; ".join(f"{r}: add {k!r}: {t!r}" for r, (k, t) in missing.items())
    )


def test_the_generic_pairing_failure_line_is_also_pre_generated():
    """announce_pair_result speaks this for any reason not in PAIR_REPLIES."""
    events = _system_events()
    fallback = "Gagal menghubungkan. Coba tekan lagi."
    assert events.get(_safe_name(fallback)) == fallback


def test_find_wav_resolves_the_name_this_test_predicts(tmp_path):
    """Pin the local copy of the rule against drift in AudioManager itself."""
    from core.audio_manager import AudioManager

    text = "Belum ada internet. Sambungkan perangkat ke WiFi dulu."
    expected = _safe_name(text)
    assert expected == "belum_ada_internet_sambungkan_perangkat_ke_wifi_dulu"

    manager = AudioManager.__new__(AudioManager)          # no device, no I/O
    manager._audio_dir = str(tmp_path)
    assert manager._find_wav(text) is None                # nothing there yet

    # generate_audio.py writes system_<key>.wav for SYSTEM_EVENTS entries.
    target = tmp_path / f"system_{expected}.wav"
    target.write_bytes(b"RIFF")
    assert manager._find_wav(text) == str(target)

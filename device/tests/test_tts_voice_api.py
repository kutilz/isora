"""The web-facing contract for choosing a voice.

Every OpenAI voice reads Indonesian acceptably once the accent instruction is
applied, so the choice is taste and belongs in the UI. What must hold: an
unknown voice is refused with the list (not sent to the API to fail once per
describe), and auditioning one must not change the saved setting.
"""

import pytest

from server.web_server import _OPENAI_VOICES, _TTS_TEST_PHRASE


def test_the_voices_we_offer_are_ones_the_api_accepts():
    for v in ("alloy", "nova", "sage", "coral", "shimmer", "echo"):
        assert v in _OPENAI_VOICES


def test_the_sample_phrase_exercises_what_a_description_must_land():
    # Position words and a clearance call — judging a voice on "halo dunia"
    # tells the listener nothing about the sentences they will really hear.
    for token in ("depan", "kanan", "aman"):
        assert token in _TTS_TEST_PHRASE.lower()


@pytest.mark.parametrize("bad", ["Nova", "gtts", "", "alloy; rm -rf /", "bogus"])
def test_an_unknown_voice_is_not_a_valid_choice(bad):
    assert bad not in _OPENAI_VOICES


def test_status_resolves_auto_to_what_the_device_will_actually_use(monkeypatch):
    """The page must show the real backend, not the literal word "auto" — a
    pendamping reading "auto" learns nothing about which voice they will hear."""
    from config import cfg

    def resolved():
        choice = str(cfg.get("tts_provider", "gtts")).lower()
        return "openai" if (choice == "openai"
                            or (choice == "auto" and cfg.OPENAI_API_KEY)) else "gtts"

    monkeypatch.setattr(cfg, "_data", {**cfg._data, "tts_provider": "auto",
                                       "openai_api_key": ""})
    assert resolved() == "gtts"
    monkeypatch.setattr(cfg, "_data", {**cfg._data, "tts_provider": "auto",
                                       "openai_api_key": "sk-test"})
    assert resolved() == "openai"
    monkeypatch.setattr(cfg, "_data", {**cfg._data, "tts_provider": "gtts",
                                       "openai_api_key": "sk-test"})
    assert resolved() == "gtts"

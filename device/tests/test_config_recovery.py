"""Config durability and the clamps on values that reach hardware.

/root/config.json holds device_token, pairing state and every *_api_key_enc.
Losing it is not recoverable from the device side, so a corrupt file must never
be overwritten unless a backup of it actually succeeded.
"""

import json

import pytest

import config as config_mod
from config import Config


@pytest.fixture
def cfg_path(tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    monkeypatch.setattr(config_mod, "_CONFIG_PATH", p)
    return p


def test_corrupt_config_is_backed_up_then_replaced(cfg_path):
    cfg_path.write_text("{not json at all")

    Config()

    assert (cfg_path.parent / "config.json.corrupt").read_text() == "{not json at all"
    assert json.loads(cfg_path.read_text())["ai_provider"]  # defaults written


def test_corrupt_config_survives_when_the_backup_fails(cfg_path, monkeypatch):
    # If the rename fails (read-only mount, EACCES, path is a directory) then
    # writing defaults would destroy the only copy of device_token and every
    # encrypted API key — exactly what the backup exists to prevent.
    original = json.dumps({"device_token": "keep-me", "openai_api_key_enc": "v1.x.y.z"})
    cfg_path.write_text(original + "  <<truncated garbage")

    def no_rename(*a, **k):
        raise OSError("read-only file system")

    monkeypatch.setattr(config_mod.os, "replace", no_rename)

    cfg = Config()

    # File left exactly as it was, for hand recovery.
    assert cfg_path.read_text() == original + "  <<truncated garbage"
    # In-memory defaults still let the device boot.
    assert cfg.get("ai_provider") is not None


def test_missing_config_writes_defaults(cfg_path):
    Config()
    assert json.loads(cfg_path.read_text())["ai_provider"]


# ── Clamps on values that reach hardware / the network ───────────────────────

@pytest.mark.parametrize("raw,want", [
    (100000, 100),   # straight to player.volume(), in a blind user's ear
    (-5, 0),
    ("not a number", 80),
    (55, 55),
])
def test_audio_volume_is_clamped_at_the_read_site(cfg_path, raw, want):
    # The cloud config push writes audio_volume without going through the
    # POST /config handler's validation at all, so the property must clamp too.
    cfg = Config()
    cfg.set("audio_volume", raw)
    assert cfg.AUDIO_VOLUME == want


@pytest.mark.parametrize("raw,want", [
    ("15s", 15),     # a bare ValueError here would escape as a non-AdapterError
    (0, 1),
    (99999, 120),
    (30, 30),
])
def test_ai_timeout_is_validated(cfg_path, raw, want):
    cfg = Config()
    cfg.set("ai_timeout_s", raw)
    assert cfg.AI_TIMEOUT_S == want


@pytest.mark.parametrize("raw,want", [
    (180, 180),
    ("90", 90),          # JSON/querystring round-trip keeps it a string
    (-90, 270),
    (450, 90),
    (45, 0),             # not a quarter turn -> leave the camera alone
    ("terbalik", 0),
    (None, 0),
])
def test_camera_rotation_is_normalized_at_the_read_site(cfg_path, raw, want):
    # This value is handed to image.rotate() on the AI loop's 30fps path, and
    # the cloud config push writes camera_rotation with no validation at all.
    cfg = Config()
    cfg.set("camera_rotation", raw)
    assert cfg.CAMERA_ROTATION == want


def test_camera_rotation_defaults_to_upright(cfg_path):
    # A config written before this key existed must not imply a turn.
    cfg = Config()
    cfg._data.pop("camera_rotation", None)
    assert cfg.CAMERA_ROTATION == 0

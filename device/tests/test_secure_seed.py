"""Device-key seed durability.

The seed is the root of the at-rest encryption for every API key. Two failure
modes matter and both are silent: a seed that is the SAME on every device
(defeating the point of encrypting at all), and a seed that CHANGES between the
encrypt and the decrypt of one key (every key reads back as "" and every adapter
reports "api_key not configured", permanently).
"""

import os

import pytest

from utils import secure_keys


@pytest.fixture
def seed_file(tmp_path, monkeypatch):
    path = str(tmp_path / "seed")
    monkeypatch.setattr(secure_keys, "_SEED_FILE", path)
    monkeypatch.setattr(secure_keys, "_fallback_seed", None)
    return path


def test_seed_is_generated_and_persisted(seed_file):
    seed = secure_keys._machine_seed()
    assert len(seed) >= secure_keys._MIN_SEED_LEN
    assert os.path.exists(seed_file)
    # Same seed on the next call — this is what makes a key survive a reboot.
    assert secure_keys._machine_seed() == seed


def test_truncated_seed_file_is_replaced_not_trusted(seed_file):
    # A power cut between O_CREAT|O_EXCL and the write leaves a 0-byte file that
    # exists (so O_EXCL keeps failing) but is unusable. Returning its contents
    # would make _device_key() the identical constant on every affected device.
    open(seed_file, "wb").close()

    seed = secure_keys._machine_seed()

    assert seed != b""
    assert len(seed) >= secure_keys._MIN_SEED_LEN
    with open(seed_file, "rb") as f:
        assert f.read() == seed          # repaired on disk, not just in memory


def test_short_seed_file_is_replaced(seed_file):
    with open(seed_file, "wb") as f:
        f.write(b"tooshort")

    seed = secure_keys._machine_seed()

    assert len(seed) >= secure_keys._MIN_SEED_LEN
    assert seed != b"tooshort"


def test_seed_is_stable_when_it_cannot_be_persisted(tmp_path, monkeypatch):
    # Read-only /root after an fsck, ENOSPC, or running non-root. Returning
    # fresh randomness here means encrypt and decrypt use different keys.
    monkeypatch.setattr(secure_keys, "_SEED_FILE", str(tmp_path / "nope" / "seed"))
    monkeypatch.setattr(secure_keys, "_fallback_seed", None)

    def boom(*a, **k):
        raise OSError("read-only file system")

    monkeypatch.setattr(secure_keys.os, "open", boom)

    first = secure_keys._machine_seed()
    second = secure_keys._machine_seed()

    assert first == second
    assert len(first) >= secure_keys._MIN_SEED_LEN


def test_fallback_never_seeds_from_a_per_boot_machine_id(tmp_path, monkeypatch):
    """dbus regenerates /var/lib/dbus/machine-id on EVERY boot on this image.

    Seeding from it looks stable — it is a machine-id, it is 32 hex chars, it is
    there — and reintroduces the whole bug: the key encrypts under boot N's uuid
    and decrypts to "" under boot N+1's. Same for boot_id, which is per-boot by
    definition. The fallback must skip both even when they are the only readable
    machine identifiers on the box.
    """
    monkeypatch.setattr(secure_keys, "_fallback_seed", None)

    per_boot = b"0f9c1d7e4b2a48c6931e5a70d8b3f612"
    opened = []
    real_open = open

    def fake_open(path, *a, **k):
        opened.append(str(path))
        if str(path) in ("/var/lib/dbus/machine-id",
                         "/proc/sys/kernel/random/boot_id"):
            raise AssertionError(f"seeded from a per-boot identifier: {path}")
        if str(path) == "/etc/machine-id":
            raise FileNotFoundError(path)      # absent on this image
        if str(path).startswith("/sys/block/"):
            raise FileNotFoundError(path)      # no SD CID on the test host
        return real_open(path, *a, **k)

    monkeypatch.setattr("builtins.open", fake_open)

    seed = secure_keys._stable_fallback_seed()

    assert seed != per_boot
    assert per_boot not in seed
    assert len(seed) >= secure_keys._MIN_SEED_LEN


def test_roundtrip_survives_an_unwritable_seed_file(tmp_path, monkeypatch):
    """The whole point: a key encrypted now still decrypts a moment later."""
    monkeypatch.setattr(secure_keys, "_SEED_FILE", str(tmp_path / "nope" / "seed"))
    monkeypatch.setattr(secure_keys, "_fallback_seed", None)

    def boom(*a, **k):
        raise OSError("read-only file system")

    monkeypatch.setattr(secure_keys.os, "open", boom)

    blob = secure_keys.encrypt("sk-secret-value")
    assert secure_keys.decrypt(blob) == "sk-secret-value"

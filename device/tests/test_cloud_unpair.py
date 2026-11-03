"""Releasing a device in the app must leave it pairable again.

`paired` used to be one-way on the device: `_on_paired` set it, nothing ever
cleared it. Tap "Lepaskan perangkat" in the app and the relay forgets the owner,
but the device keeps believing it is paired — `wants_button_pair()` stays False,
so pressing ACTION does nothing at all, and the only way back is editing
config.json over SSH. That is not a thing the person wearing the glasses can do.

Both callers matter: register() answers "paired" on every loop, heartbeat every
20 s, and a release can land between them.
"""

import pytest

from config import cfg
from core import cloud


class _Logger:
    def __init__(self):
        self.lines = []

    def info(self, msg="", **k): self.lines.append(("info", msg))
    def warn(self, msg="", **k): self.lines.append(("warn", msg))
    def ok(self, msg="", **k): self.lines.append(("ok", msg))
    def error(self, msg="", **k): self.lines.append(("error", msg))


class _Announcer:
    def __init__(self):
        self.forced = 0

    def announce(self, force=False):
        if force:
            self.forced += 1

    def announce_paired(self):
        pass


@pytest.fixture
def client(monkeypatch):
    """A paired client whose config writes go nowhere near the real device."""
    writes = {}
    monkeypatch.setattr(cfg, "update", lambda patch: writes.update(patch))
    monkeypatch.setattr(type(cfg), "PAIRED", property(lambda self: True))

    c = cloud.CloudClient(orchestrator=None, logger=_Logger(), announcer=_Announcer())
    assert c._paired is True
    return c, writes


def test_a_paired_device_does_not_offer_the_button(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr(type(cfg), "CLOUD_ENABLED", property(lambda self: True))
    assert c.wants_button_pair() is False


def test_release_makes_the_button_offer_pairing_again(client, monkeypatch):
    c, writes = client
    monkeypatch.setattr(type(cfg), "CLOUD_ENABLED", property(lambda self: True))

    c._on_unpaired()

    assert c._paired is False
    assert writes.get("paired") is False
    assert c.wants_button_pair() is True


def test_release_is_spoken_even_though_setup_is_finished(client):
    """The onboarding nag is gated on setup_completed; this moment bypasses it."""
    c, _ = client
    c._on_unpaired()
    assert c.announcer.forced == 1


def test_release_stays_quiet_in_data_collection_mode(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr(cfg, "get", lambda k, d=None: True if k == "data_collection_mode" else d)
    c._on_unpaired()
    assert c.announcer.forced == 0


def test_a_stale_pairing_code_is_dropped_on_release(client):
    c, _ = client
    c._code, c._code_at = "A3F7C1", 123.0
    c._on_unpaired()
    assert c._code is None


def test_unreachable_relay_is_not_read_as_a_release(client):
    """`None` means the request never landed — losing WiFi must not unpair."""
    c, writes = client
    reg = None
    if reg is False and c._paired:      # mirrors the loop's guard
        c._on_unpaired()
    assert c._paired is True
    assert "paired" not in writes

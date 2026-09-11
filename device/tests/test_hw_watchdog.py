"""The hardware watchdog is the only thing that can recover a GIL-wedged board.

It is also the most dangerous code in the tree: petting it wrongly turns a rare
hang into a reboot loop on a device someone depends on. Verified on hardware —
opening /dev/watchdog on this SoC arms it immediately and really does reset the
board — so these tests pin the safety properties rather than the mechanism.
"""

import os
import threading

import pytest

from utils import hw_watchdog as hw


class _FakeFd:
    """Stands in for the /dev/watchdog file descriptor."""

    def __init__(self):
        self.writes = []
        self.closed = False


class _Os:
    """Minimal os shim so no test ever opens a real watchdog device."""

    O_WRONLY = os.O_WRONLY

    def __init__(self, exists=True, open_raises=False):
        self.fd = _FakeFd()
        self._exists = exists
        self._open_raises = open_raises
        self.opened = []

    def path_exists(self, p):
        return self._exists

    def open(self, path, _flags):
        if self._open_raises:
            raise PermissionError("nope")
        self.opened.append(path)
        return 7

    def write(self, fd, data):
        assert fd == 7
        self.fd.writes.append(data)
        return len(data)

    def close(self, fd):
        assert fd == 7
        self.fd.closed = True


@pytest.fixture
def fake_os(monkeypatch):
    shim = _Os()
    monkeypatch.setattr(hw.os, "open", shim.open)
    monkeypatch.setattr(hw.os, "write", shim.write)
    monkeypatch.setattr(hw.os, "close", shim.close)
    monkeypatch.setattr(hw.os.path, "exists", shim.path_exists)
    # Keep the ioctl out of it: SETTIMEOUT is best-effort by design.
    monkeypatch.setattr(hw.HardwareWatchdog, "_set_timeout", lambda self: None)
    return shim


def test_it_pets_before_anything_else(fake_os):
    """Opening the node starts the countdown, so the FIRST thing after open()
    must be a pet — not an ioctl, not a log line."""
    wd = hw.HardwareWatchdog(pet_interval_s=60, is_alive_fn=lambda: True)
    assert wd.start() is True
    try:
        assert fake_os.fd.writes, "nothing was written after arming"
        assert fake_os.fd.writes[0] == b"\0"
    finally:
        wd.stop()


def test_it_stops_petting_once_the_loop_goes_stale(fake_os):
    """A wedged AI loop must be allowed to reach the reset."""
    alive = threading.Event()
    alive.set()
    wd = hw.HardwareWatchdog(pet_interval_s=0.01, is_alive_fn=alive.is_set)
    assert wd.start() is True
    try:
        threading.Event().wait(0.1)
        assert len(fake_os.fd.writes) > 1

        alive.clear()
        settled = len(fake_os.fd.writes)
        threading.Event().wait(0.15)
        assert len(fake_os.fd.writes) == settled, (
            "kept petting a dead loop — the board would never recover")
    finally:
        wd.stop()


def test_petting_resumes_if_the_loop_recovers(fake_os):
    alive = threading.Event()
    wd = hw.HardwareWatchdog(pet_interval_s=0.01, is_alive_fn=alive.is_set)
    assert wd.start() is True
    try:
        threading.Event().wait(0.08)
        stalled = len(fake_os.fd.writes)
        alive.set()
        threading.Event().wait(0.1)
        assert len(fake_os.fd.writes) > stalled
    finally:
        wd.stop()


def test_a_liveness_probe_that_throws_keeps_the_board_up(fake_os):
    """A broken health check is not evidence the device is dead."""
    def _boom():
        raise RuntimeError("probe exploded")

    wd = hw.HardwareWatchdog(pet_interval_s=0.01, is_alive_fn=_boom)
    assert wd.start() is True
    try:
        threading.Event().wait(0.08)
        assert len(fake_os.fd.writes) > 1
    finally:
        wd.stop()


def test_clean_stop_disarms_with_the_magic_close(fake_os):
    """Without the 'V' a deliberate shutdown still resets the board later."""
    wd = hw.HardwareWatchdog(pet_interval_s=60, is_alive_fn=lambda: True)
    wd.start()
    wd.stop(disarm=True)
    assert fake_os.fd.writes[-1] == b"V"
    assert fake_os.fd.closed is True


def test_stop_without_disarm_does_not_write_the_magic_char(fake_os):
    wd = hw.HardwareWatchdog(pet_interval_s=60, is_alive_fn=lambda: True)
    wd.start()
    wd.stop(disarm=False)
    assert b"V" not in fake_os.fd.writes
    assert fake_os.fd.closed is True


def test_a_board_without_a_watchdog_still_boots(monkeypatch):
    monkeypatch.setattr(hw.os.path, "exists", lambda _p: False)
    wd = hw.HardwareWatchdog()
    assert wd.start() is False


def test_an_unopenable_node_still_boots(monkeypatch):
    monkeypatch.setattr(hw.os.path, "exists", lambda _p: True)

    def _deny(*_a, **_k):
        raise PermissionError("nope")

    monkeypatch.setattr(hw.os, "open", _deny)
    assert hw.HardwareWatchdog().start() is False


# ── the opt-in gate ──────────────────────────────────────────────────────────

class _Cfg(dict):
    def get(self, k, d=None):
        return dict.get(self, k, d)


def test_it_is_off_unless_the_unit_opts_in(fake_os):
    assert hw.start_if_enabled(_Cfg(), logger=None) is None
    assert hw.start_if_enabled(_Cfg({"hw_watchdog_enabled": False})) is None
    assert fake_os.opened == [], "armed a watchdog nobody asked for"


def test_opting_in_arms_it(fake_os):
    wd = hw.start_if_enabled(
        _Cfg({"hw_watchdog_enabled": True, "hw_watchdog_pet_s": 60}),
        is_alive_fn=lambda: True,
    )
    assert wd is not None
    try:
        assert fake_os.opened, "opt-in did not open the device"
    finally:
        wd.stop()


def test_a_broken_config_never_breaks_boot(fake_os):
    class _Angry:
        def get(self, *_a, **_k):
            raise RuntimeError("config on fire")

    assert hw.start_if_enabled(_Angry()) is None

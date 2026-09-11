"""HealthMonitor's feed to the power governor.

The old contract fired only on threshold crossings — enough for "shout once",
useless for a governor that has to track a trend, hold a tier through
hysteresis and ease back down. So the monitor now hands over every sample.
"""

import time

import utils.health as health_mod
from utils.health import HealthMonitor


def _fixed_health(temp_c):
    return lambda: {"cpu_temp_c": temp_c, "ram_used_pct": 40}


def test_every_poll_reaches_the_listener(monkeypatch):
    monkeypatch.setattr(health_mod, "get_health", _fixed_health(61.5))
    seen = []
    mon  = HealthMonitor(poll_interval_s=0.01)
    mon.start(on_sample=lambda snap: seen.append(snap["cpu_temp_c"]))
    try:
        deadline = time.monotonic() + 2.0
        while len(seen) < 3 and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        mon.stop()
    assert len(seen) >= 3
    assert seen[0] == 61.5


def test_a_listener_that_raises_does_not_kill_the_monitor(monkeypatch):
    # The governor runs inside this thread. If one bad sample could end the
    # monitor, the device would silently stop adapting for the rest of its run.
    monkeypatch.setattr(health_mod, "get_health", _fixed_health(70.0))
    calls = []

    def _boom(snap):
        calls.append(snap)
        raise RuntimeError("governor blew up")

    mon = HealthMonitor(poll_interval_s=0.01)
    mon.start(on_sample=_boom)
    try:
        deadline = time.monotonic() + 2.0
        while len(calls) < 3 and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        mon.stop()
    assert len(calls) >= 3

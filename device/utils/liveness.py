"""
Heartbeat file for the app supervisor (device/system/supervise.sh).

The supervisor runs OUTSIDE this process, which is the whole point: when a
camera/NPU call blocks holding the GIL, every thread in here stops — the
in-process Watchdog included — and only something outside can end the
process and start it again. This module is how it can tell.

A thread rewrites ALIVE_PATH every few seconds while `is_alive_fn()` says the
AI loop is still ticking. It stops writing when the loop goes stale (stuck,
but the GIL is free) and, necessarily, when the whole process is wedged. The
supervisor kills the app once the file is older than its STALE_S.

The file holds the uptime from /proc/uptime, not a wall-clock time and not an
mtime: S03isoraclock and NTP move the clock by years after boot, and a jump
would read as a heartbeat decades old.

mark_stopping() tells the supervisor a shutdown is deliberate, so a slow
camera release on the way out is not mistaken for a wedge — and the exit that
follows is not restarted.

Never raises: no /proc/uptime (a PC) or an unwritable /tmp just means nothing
is supervised, which is how the app ran before.
"""

import os
import threading

ALIVE_PATH = "/tmp/isora_alive"
STOPPING_PATH = "/tmp/isora_stopping"


def _read_uptime(path="/proc/uptime"):
    try:
        with open(path) as f:
            return f.read().split()[0]
    except Exception:
        return None


def _write_atomic(path, text):
    tmp = "%s.%d" % (path, os.getpid())
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, path)


class LivenessBeacon:
    """Rewrites `path` every `interval_s` while `is_alive_fn()` is True."""

    def __init__(self, is_alive_fn=None, interval_s: float = 5.0,
                 path: str = ALIVE_PATH, uptime_fn=None):
        self.is_alive_fn = is_alive_fn
        self.interval_s = float(interval_s)
        self.path = path
        self._uptime = uptime_fn or _read_uptime
        self._stop = threading.Event()
        self._thread = None

    def healthy(self) -> bool:
        if self.is_alive_fn is None:
            return True
        try:
            return bool(self.is_alive_fn())
        except Exception:
            # A probe that throws is not evidence of a wedge; killing a working
            # app on stage over it would be the worse failure.
            return True

    def beat_once(self) -> bool:
        """Write one heartbeat if the loop is healthy. True when written."""
        if not self.healthy():
            return False
        up = self._uptime()
        if up is None:
            return False
        try:
            _write_atomic(self.path, up + "\n")
            return True
        except Exception:
            return False

    def start(self) -> bool:
        """Start beating. False (and no thread) when there is no uptime source."""
        if self._uptime() is None:
            return False
        self.beat_once()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="Liveness")
        self._thread.start()
        return True

    def _loop(self):
        while not self._stop.wait(self.interval_s):
            self.beat_once()

    def stop(self):
        self._stop.set()


def mark_stopping(path: str = STOPPING_PATH) -> bool:
    """Tell the supervisor this shutdown is on purpose. Never raises."""
    try:
        _write_atomic(path, "stop\n")
        return True
    except Exception:
        return False

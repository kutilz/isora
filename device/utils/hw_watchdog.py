"""
SoC hardware watchdog — the only thing that can recover a GIL-wedged device.

Why this exists
---------------
The in-process Watchdog (core/watchdog.py) supervises Python modules and can
restart them. It cannot help with the failure this device actually hits: the
camera/NPU teardown is a C call that holds the GIL, so when it blocks, EVERY
Python thread stops — including the watchdog thread itself. Measured in the
field: the app froze inside AIEngine.release(), never logged again, kept the
HTTP server answering stale JSON for minutes, and left the audio codec looping
one phrase into a blind user's ear with the buttons dead. Only unplugging the
power stopped it.

A watchdog that runs inside the wedged process can never fix that. The SoC's
hardware watchdog can: it counts down in silicon, and if nobody pets it, it
resets the board.

Danger, and how this module handles it
--------------------------------------
Opening /dev/watchdog ARMS it immediately — on this SoC with a short default
timeout. Get the petting wrong and the device reboot-loops, which is strictly
worse than the hang it is meant to fix. Confirmed on hardware: a probe that
opened the node and spent a few seconds on ioctls reset the board.

So the ordering here is deliberate:

  1. open the device,
  2. start petting BEFORE anything else — no ioctl, no logging, no config read
     happens between the open and the first pet,
  3. only then try to widen the timeout (best effort; a driver that refuses
     just keeps its default, and the fast pet interval already covers it).

`is_alive_fn` is what makes this a supervisor rather than a timer: the pet
thread stops petting when the AI loop's heartbeat goes stale, which is exactly
the wedged-process case. A healthy but busy loop must not trip it, so
`stale_after_s` is generous — a slow cloud describe can legitimately hold a
tick for tens of seconds.

Clean shutdown writes the 'V' magic character, which is the documented way to
tell the driver to DISARM. Without it, a deliberate stop would still reset the
board one timeout later.

DEFAULT OFF. cfg["hw_watchdog_enabled"] must be set explicitly, per unit, after
someone has watched a unit run with it armed. An unvalidated auto-reset on a
device someone depends on is not a safe default.
"""

import os
import threading
import time

_WATCHDOG_PATHS = ("/dev/watchdog", "/dev/watchdog0")

# linux/watchdog.h — WDIOC_SETTIMEOUT / WDIOC_GETTIMEOUT
_WDIOC_SETTIMEOUT = 0xC0045706
_WDIOC_GETTIMEOUT = 0x80045707

_MAGIC_CLOSE = b"V"


class HardwareWatchdog:
    """Pets /dev/watchdog while `is_alive_fn()` keeps returning True."""

    def __init__(self, logger=None, timeout_s: int = 60,
                 pet_interval_s: float = 2.0, stale_after_s: float = 45.0,
                 is_alive_fn=None, path: str = None):
        self.logger         = logger
        self.timeout_s      = int(timeout_s)
        self.pet_interval_s = float(pet_interval_s)
        self.stale_after_s  = float(stale_after_s)
        self.is_alive_fn    = is_alive_fn
        self.path           = path
        self._fd            = None
        self._stop          = threading.Event()
        self._thread        = None
        self._starved_since = None

    # ── logging helpers (never raise) ────────────────────────────────────────

    def _log(self, level, msg):
        if self.logger is None:
            return
        try:
            getattr(self.logger, level)(msg, module="HWWatchdog")
        except Exception:
            pass

    @staticmethod
    def available(paths=_WATCHDOG_PATHS) -> bool:
        """True when this board exposes a watchdog device node."""
        return any(os.path.exists(p) for p in paths)

    @staticmethod
    def _first_path(paths=_WATCHDOG_PATHS):
        for p in paths:
            if os.path.exists(p):
                return p
        return None

    # ── lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> bool:
        """Arm the watchdog and begin petting. Returns True when armed.

        Never raises: a board without a usable watchdog must still boot.
        """
        path = self.path or self._first_path()
        if not path:
            self._log("info", "No /dev/watchdog on this board — not armed")
            return False
        try:
            fd = os.open(path, os.O_WRONLY)
        except Exception as e:
            self._log("warn", f"Cannot open {path}: {e} — not armed")
            return False

        self._fd = fd
        # Pet FIRST. The device is already counting down; anything that costs
        # time between open() and the first pet is time the board can reset in.
        self._pet_once()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="HWWatchdog"
        )
        self._thread.start()
        self._set_timeout()
        self._log("ok", f"Hardware watchdog armed via {path} "
                        f"(timeout {self.timeout_s}s, pet {self.pet_interval_s}s, "
                        f"stale {self.stale_after_s}s)")
        return True

    def _set_timeout(self):
        """Widen the driver timeout. Best effort — the pet interval is what
        actually keeps the board alive, so a refusal here is not fatal."""
        try:
            import array
            import fcntl
            v = array.array("i", [self.timeout_s])
            fcntl.ioctl(self._fd, _WDIOC_SETTIMEOUT, v, True)
            got = array.array("i", [0])
            fcntl.ioctl(self._fd, _WDIOC_GETTIMEOUT, got, True)
            if got[0] and got[0] != self.timeout_s:
                self._log("info", f"Driver clamped watchdog timeout to {got[0]}s")
                self.timeout_s = got[0]
        except Exception as e:
            self._log("info", f"Watchdog SETTIMEOUT unavailable ({e}) — "
                              f"using the driver default")

    def _pet_once(self) -> bool:
        if self._fd is None:
            return False
        try:
            os.write(self._fd, b"\0")
            return True
        except Exception as e:
            self._log("warn", f"Watchdog pet failed: {e}")
            return False

    def healthy(self) -> bool:
        """Whether the supervised loop still counts as alive."""
        if self.is_alive_fn is None:
            return True
        try:
            return bool(self.is_alive_fn())
        except Exception:
            # A liveness probe that itself throws is not evidence of death —
            # keep the board up and let the error be someone else's problem.
            return True

    def _loop(self):
        while not self._stop.is_set():
            if self.healthy():
                if self._starved_since is not None:
                    self._log("ok", "AI loop heartbeat recovered — petting resumed")
                    self._starved_since = None
                self._pet_once()
            else:
                now = time.monotonic()
                if self._starved_since is None:
                    self._starved_since = now
                    self._log("error",
                              "AI loop heartbeat stale — NOT petting the "
                              "hardware watchdog. The board will reset in about "
                              f"{self.timeout_s}s unless it recovers.")
            self._stop.wait(self.pet_interval_s)

    def stop(self, disarm: bool = True):
        """Stop petting. `disarm` writes the magic 'V' so a deliberate shutdown
        does not leave the board to reset one timeout later."""
        self._stop.set()
        if self._thread is not None:
            try:
                self._thread.join(timeout=self.pet_interval_s + 1.0)
            except Exception:
                pass
        if self._fd is None:
            return
        try:
            if disarm:
                os.write(self._fd, _MAGIC_CLOSE)
        except Exception:
            pass
        try:
            os.close(self._fd)
        except Exception:
            pass
        self._fd = None


def start_if_enabled(cfg, logger=None, is_alive_fn=None):
    """Arm the hardware watchdog when the unit opts in. Returns it, or None.

    Off unless cfg["hw_watchdog_enabled"] is true. See the module docstring:
    an auto-reset nobody has watched run is not something to switch on for a
    whole fleet by default.
    """
    try:
        if not cfg.get("hw_watchdog_enabled", False):
            return None
    except Exception:
        return None
    try:
        wd = HardwareWatchdog(
            logger=logger,
            timeout_s=int(cfg.get("hw_watchdog_timeout_s", 60)),
            pet_interval_s=float(cfg.get("hw_watchdog_pet_s", 2.0)),
            stale_after_s=float(cfg.get("hw_watchdog_stale_s", 45.0)),
            is_alive_fn=is_alive_fn,
        )
    except Exception:
        return None
    return wd if wd.start() else None

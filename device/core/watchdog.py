"""
Watchdog — monitors registered modules via periodic heartbeat.

Each module calls wd.heartbeat(name) from its main loop.
If a module misses max_misses consecutive checks (each separated by
check_interval_s), its restart_fn is invoked automatically.
"""

import time
import threading
from typing import Callable, Dict, Optional


class _Entry:
    __slots__ = ("name", "timeout_s", "restart_fn", "max_misses",
                 "last_beat", "misses")

    def __init__(self, name: str, timeout_s: float,
                 restart_fn: Callable, max_misses: int):
        self.name       = name
        self.timeout_s  = timeout_s
        self.restart_fn = restart_fn
        self.max_misses = max_misses
        self.last_beat  = time.monotonic()
        self.misses     = 0


class Watchdog:
    """
    Usage example::

        wd = Watchdog()
        wd.start()
        wd.register("ai_engine", timeout_s=5.0, restart_fn=engine.reload)

        # Inside the AI loop, once per iteration:
        wd.heartbeat("ai_engine")
    """

    def __init__(self, check_interval_s: float = 1.0):
        self._interval = check_interval_s
        self._entries:  Dict[str, _Entry] = {}
        self._lock      = threading.Lock()
        self._stop      = threading.Event()
        self._thread    = threading.Thread(
            target=self._loop, daemon=True, name="Watchdog"
        )

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    # ─── Registration ─────────────────────────────────────────────────────────

    def register(self, name: str, timeout_s: float,
                 restart_fn: Callable, max_misses: int = 3):
        """Register a module. restart_fn must be safe to call from any thread."""
        with self._lock:
            self._entries[name] = _Entry(name, timeout_s, restart_fn, max_misses)

    def unregister(self, name: str):
        with self._lock:
            self._entries.pop(name, None)

    # ─── Heartbeat ────────────────────────────────────────────────────────────

    def heartbeat(self, name: str):
        """Reset the watchdog timer for the named module."""
        with self._lock:
            if name in self._entries:
                e = self._entries[name]
                e.last_beat = time.monotonic()
                e.misses    = 0

    # ─── Status ───────────────────────────────────────────────────────────────

    def status(self) -> dict:
        now = time.monotonic()
        with self._lock:
            return {
                n: {
                    "last_beat_s_ago": round(now - e.last_beat, 1),
                    "timeout_s":       e.timeout_s,
                    "misses":          e.misses,
                    "healthy":         (now - e.last_beat) <= e.timeout_s,
                }
                for n, e in self._entries.items()
            }

    # ─── Internal loop ────────────────────────────────────────────────────────

    def _loop(self):
        while not self._stop.wait(self._interval):
            now = time.monotonic()
            with self._lock:
                entries = list(self._entries.values())

            for e in entries:
                if now - e.last_beat > e.timeout_s:
                    e.misses += 1
                    if e.misses >= e.max_misses:
                        # Reset before calling restart_fn to avoid re-triggering
                        # if the function itself takes longer than one interval.
                        e.misses    = 0
                        e.last_beat = now
                        try:
                            e.restart_fn()
                        except Exception:
                            pass

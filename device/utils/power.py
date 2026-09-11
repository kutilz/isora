"""Adaptive power/thermal governor.

Turns a temperature reading into a *work budget* for the AI loop.
"""

from typing import NamedTuple, Optional


def _valid_temp(raw) -> Optional[float]:
    """A usable °C reading, or None when the sensor said nothing believable.

    `get_health()` yields 0.0 when /sys/class/thermal is missing entirely, and
    a dead zone can report negatives or NaN. None means "no new information" —
    the governor then keeps whatever it last decided rather than guessing.
    """
    try:
        t = float(raw)
    except (TypeError, ValueError):
        return None
    if t != t or t <= 0.0 or t > 200.0:   # NaN, empty sensor, absurd value
        return None
    return t


class PowerPlan(NamedTuple):
    tier:       str
    target_fps: float
    preview:    bool

    @property
    def frame_interval_s(self) -> float:
        """Seconds one paced cycle is allowed to occupy."""
        return 1.0 / self.target_fps if self.target_fps > 0 else 0.0


def pace_delay(plan: PowerPlan, elapsed_s: float) -> float:
    """How long the AI loop must idle to hit `plan.target_fps`.

    This is where a plan stops being advice and becomes heat the SoC never
    generates: the difference between the tick's budget and what it actually
    spent. Never negative — a tick that already overran just goes straight on.
    """
    return max(0.0, plan.frame_interval_s - max(0.0, elapsed_s))


# Tiers, coolest first. Each carries the work it is willing to pay for:
#   fps      frames per second the AI loop is paced to
#   preview  encode the JPEG the dashboard shows (pure overhead when walking)
# Offsets are relative to hot_c so one threshold tunes the whole ladder.
#
# Frame rate is deliberately the ONLY work lever. An earlier draft also skipped
# inference on some frames, which is both redundant (pacing already cuts
# inferences proportionally, and inference dominates a tick — capture is ~1ms
# against ~17ms) and dangerous: a skipped frame that reports no detections
# reads downstream as "the obstacle went away".
_TIERS = (
    # name,       offset from hot_c, fps, preview
    ("normal",    None,  None, True),
    ("warm",      -6.0,  12.0, True),
    ("hot",        0.0,   6.0, False),
    ("critical",  +8.0,   2.0, False),
)
_TIER_ORDER = [t[0] for t in _TIERS]


class PowerGovernor:
    """Decides how much work the AI loop may do, from temperature alone.

    Deliberately silent: it returns a plan and never speaks, logs, or touches
    hardware. A device strapped to a walking person cannot answer heat by
    asking its user to intervene — it answers by doing less.
    """

    def __init__(self, full_fps: int = 30, hot_c: float = 80.0,
                 recover_margin_c: float = 5.0,
                 idle_after_s: float = 20.0, idle_fps: float = 8.0):
        self._full_fps    = full_fps
        self._hot_c       = hot_c
        self._margin      = recover_margin_c
        self._idle_after  = idle_after_s
        self._idle_fps    = idle_fps
        self._tier        = "normal"
        self._last_busy_t = None      # None until the first update() lands
        self._idle        = False

    def _enter_temp(self, tier_index: int) -> float:
        return self._hot_c + _TIERS[tier_index][1]

    def _tier_for(self, temp_c: float) -> str:
        """Highest tier whose entry temperature is reached, with hysteresis.

        Climbing needs the entry temperature; falling back needs to clear it by
        recover_margin_c. Without that gap a reading sitting on a boundary
        retimes the loop every poll.
        """
        current = _TIER_ORDER.index(self._tier)
        target  = 0
        for i in range(1, len(_TIERS)):
            enter = self._enter_temp(i)
            # A tier we are already in (or above) holds until temp drops a full
            # margin below its entry point.
            threshold = enter - self._margin if i <= current else enter
            if temp_c >= threshold:
                target = i
        return _TIER_ORDER[target]

    def update(self, temp_c=None, now: float = 0.0, busy: bool = True) -> PowerPlan:
        """Fold one poll (temperature + whether anything is happening) into a plan."""
        reading = _valid_temp(temp_c)
        if reading is not None:
            self._tier = self._tier_for(reading)
        self._update_idle(now, busy)
        return self._plan()

    def _update_idle(self, now: float, busy: bool):
        """Track how long the scene has been empty.

        Waking is deliberately asymmetric: settling into the low rate takes
        idle_after_s of nothing at all, leaving it takes one busy frame. The
        event that ends a quiet stretch is the obstacle the user must hear
        about, so it can never be the one that waits.
        """
        if busy or self._last_busy_t is None:
            self._last_busy_t = now
            self._idle = False
            return
        self._idle = (now - self._last_busy_t) >= self._idle_after

    def _plan(self) -> PowerPlan:
        name, _off, fps, preview = _TIERS[_TIER_ORDER.index(self._tier)]
        target = self._full_fps if fps is None else min(fps, self._full_fps)
        if self._idle:
            # Heat always wins: idling may lower the rate, never raise it back
            # over what the thermal tier already decided to allow.
            target = min(target, self._idle_fps)
        return PowerPlan(tier=name, target_fps=target, preview=preview)

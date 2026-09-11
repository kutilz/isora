"""Distance band: collapse raw box area into a coarse near/far tier per object
class, with a ground-contact nudge and boundary hysteresis.

Decision 5A: TWO tiers only (near/far). The near cutoff is per-class because a
"car" filling 15% of the frame is still far (cars are big) while a "bottle"
filling 15% is right under your nose. `band()` is pure (no clock, no I/O); the
only state is the caller-supplied `prev_tier`, which drives hysteresis so an
object hovering on the boundary doesn't flap near<->far every frame.
"""

from utils.distance import band, NEAR_AREA_THRESHOLDS, DEFAULT_NEAR_AREA


# A bottom-of-box well up the frame (small fraction) = no ground nudge, so the
# pure area threshold is what we're probing in most tests.
HIGH = 0.30   # box bottom near top of frame -> far away on the ground
LOW = 0.95    # box bottom near frame bottom -> right in front of the user


def test_degenerate_bbox_is_far():
    # area_ratio <= 0 is a junk/empty box -> never call it near.
    assert band("person", 0.0, LOW) == "far"
    assert band("car", -0.1, LOW) == "far"


def test_per_class_thresholds_differ():
    # Same area, same (neutral) ground position: a small object reads near while
    # a big object the same apparent size is still far. This is the whole point
    # of per-class tiers.
    area = 0.15
    assert band("bottle", area, HIGH) == "near"
    assert band("car", area, HIGH) == "far"


def test_known_classes_have_distinct_defaults():
    # The defaults must actually encode "small object -> near sooner".
    assert NEAR_AREA_THRESHOLDS["bottle"] < NEAR_AREA_THRESHOLDS["person"]
    assert NEAR_AREA_THRESHOLDS["person"] < NEAR_AREA_THRESHOLDS["car"]


def test_unknown_class_uses_default_threshold():
    # A label we have no calibration for falls back to DEFAULT_NEAR_AREA.
    just_over = DEFAULT_NEAR_AREA + 0.05
    just_under = DEFAULT_NEAR_AREA - 0.02
    assert band("zebra", just_over, HIGH) == "near"
    assert band("zebra", just_under, HIGH) == "far"


def test_ground_hint_pulls_borderline_box_to_near():
    # Same area, just under the bare threshold: a box whose bottom sits low in
    # the frame (closer to the ground in front of you) should tip to "near"
    # while the same box higher up stays "far".
    thr = NEAR_AREA_THRESHOLDS["person"]
    area = thr * 0.85  # below the bare cutoff
    assert band("person", area, HIGH) == "far"
    assert band("person", area, LOW) == "near"


def test_ground_hint_cannot_rescue_a_tiny_box():
    # The ground nudge is a nudge, not an override: a genuinely tiny box stays
    # far even when its bottom is at the very bottom of the frame.
    assert band("person", 0.001, LOW) == "far"


def test_hysteresis_holds_near_through_minor_dip():
    # Already near; area dips slightly below the bare threshold but not past the
    # exit band -> stays near (no flap).
    thr = NEAR_AREA_THRESHOLDS["person"]
    assert band("person", thr * 0.97, HIGH, prev_tier="near") == "near"


def test_hysteresis_requires_clear_crossing_to_enter_near():
    # Currently far; area nudges just over the bare threshold but not past the
    # enter band -> stays far until it's clearly crossed.
    thr = NEAR_AREA_THRESHOLDS["person"]
    assert band("person", thr * 1.03, HIGH, prev_tier="far") == "far"
    # A decisive crossing does switch.
    assert band("person", thr * 1.30, HIGH, prev_tier="far") == "near"


def test_boundary_hover_yields_single_transition():
    # The anti-spam guarantee: feed a sequence of areas oscillating tightly
    # around the threshold and count tier changes. With hysteresis there must be
    # at most ONE transition, not one per frame.
    thr = NEAR_AREA_THRESHOLDS["person"]
    # tiny oscillation around the bare cutoff, then a real approach at the end
    seq = [0.98, 1.02, 0.99, 1.01, 0.97, 1.03, 0.98, 1.40]
    areas = [thr * m for m in seq]

    prev = "far"
    transitions = 0
    for a in areas:
        tier = band("person", a, HIGH, prev_tier=prev)
        if tier != prev:
            transitions += 1
        prev = tier
    assert transitions == 1
    assert prev == "near"  # the final decisive approach landed us near


def test_no_prev_tier_uses_bare_threshold():
    # First sighting (prev_tier=None) has no hysteresis band to bias it: a box
    # clearly over the threshold is near, clearly under is far.
    thr = NEAR_AREA_THRESHOLDS["person"]
    assert band("person", thr * 1.5, HIGH) == "near"
    assert band("person", thr * 0.5, HIGH) == "far"


def test_cfg_override_of_thresholds():
    # Reviewers calibrate on-device via config without editing code.
    class FakeCfg:
        def __init__(self, d):
            self._d = d

        def get(self, k, default=None):
            return self._d.get(k, default)

    # Force person's near cutoff way up so a normally-near box reads far.
    cfg = FakeCfg({"distance_near_area": {"person": 0.90}})
    assert band("person", 0.20, HIGH, cfg=cfg) == "far"

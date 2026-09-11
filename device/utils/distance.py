"""Distance band — collapse a detection's raw box geometry into ONE of two
coarse tiers: "near" or "far" (Decision 5A; deliberately not three).

Why per-class, not a single global area cutoff:
    Box area alone lies about distance because objects differ in real size. A
    car filling 15% of the frame is still metres away; a bottle filling 15% is
    right under your nose. So the area at which something becomes "near" is
    per-class — big things need to fill more frame to count as close.

Ground-contact hint:
    YOLO area is noisy, so we add a cheap monocular cue: where the *bottom* of
    the box sits. An object resting on the floor right in front of you has its
    base low in the frame (bbox_bottom_norm -> 1.0); the same apparent-size box
    floating high up is further away. A low base nudges a borderline box toward
    "near" — a nudge, never an override (a tiny box stays far).

Hysteresis (anti-spam, T11):
    An object hovering on the boundary must NOT flap far<->near every frame
    (each flip is a spoken "dekat"/"jauh"). We use separate enter/exit bands: to
    switch INTO near the area must clear the threshold by +margin; to drop back
    to far it must fall below threshold by -margin. Inside the band the previous
    tier sticks. `prev_tier=None` (first sighting) has no band — it just uses the
    bare threshold.

Pure & stateless: no clock, no I/O, no `maix`. The only "state" is the
caller-supplied `prev_tier`, so this stays trivially testable off-device.
"""

# Per-class area_ratio at which an object becomes "near" (bare threshold, before
# the ground nudge / hysteresis band). These are FIRST-GUESS values to calibrate
# on-device — see test_distance.py and the module docstring. Ordering matters
# more than absolute values: small real-world objects cross to "near" at a
# smaller apparent area than big ones.
NEAR_AREA_THRESHOLDS = {
    # small / handheld — near as soon as they're a modest blob in view
    "bottle":     0.04,
    "handbag":    0.05,
    "backpack":   0.06,
    "cat":        0.06,
    # mid-size — person is the reference class
    "dog":        0.10,
    "chair":      0.12,
    "person":     0.15,
    "bicycle":    0.16,
    "motorcycle": 0.18,
    # large vehicles — must fill a lot of frame to actually be close
    "car":        0.30,
    "truck":      0.38,
    "bus":        0.40,
}

# Fallback near-cutoff for any label we haven't calibrated.
DEFAULT_NEAR_AREA = 0.15

# Ground-contact nudge: how far below the bare threshold a box may still be
# pulled up to "near" when its base sits at the very bottom of the frame. The
# effective discount scales with how low the box bottom is (see _ground_discount).
GROUND_NUDGE_MAX = 0.25       # at most a 25% lower effective cutoff
GROUND_NUDGE_START = 0.55     # bottoms above this (higher in frame) get no nudge

# Hysteresis half-width (fraction of the threshold). Enter near above
# thr*(1+H); exit to far below thr*(1-H); the band between sticks to prev_tier.
HYSTERESIS_MARGIN = 0.10


def _threshold_for(label, cfg):
    """Per-class near cutoff, overridable via cfg key ``distance_near_area``
    (a label->threshold dict). Unknown labels fall back to DEFAULT_NEAR_AREA
    (also overridable via ``distance_near_area_default``)."""
    overrides = {}
    default = DEFAULT_NEAR_AREA
    if cfg is not None:
        overrides = cfg.get("distance_near_area", {}) or {}
        default = cfg.get("distance_near_area_default", DEFAULT_NEAR_AREA)
    if label in overrides:
        return float(overrides[label])
    if label in NEAR_AREA_THRESHOLDS:
        return float(NEAR_AREA_THRESHOLDS[label])
    return float(default)


def _ground_discount(bbox_bottom_norm, cfg):
    """Fraction to shave off the near cutoff based on how low the box base sits.

    Returns 0 when the base is high in the frame (far on the ground) and ramps
    linearly up to GROUND_NUDGE_MAX as the base approaches the frame bottom
    (bbox_bottom_norm -> 1.0). Clamped to [0, max]."""
    nudge_max = GROUND_NUDGE_MAX
    start = GROUND_NUDGE_START
    if cfg is not None:
        nudge_max = float(cfg.get("distance_ground_nudge_max", GROUND_NUDGE_MAX))
        start = float(cfg.get("distance_ground_nudge_start", GROUND_NUDGE_START))
    if bbox_bottom_norm <= start or nudge_max <= 0:
        return 0.0
    span = 1.0 - start
    if span <= 0:
        return nudge_max
    frac = (bbox_bottom_norm - start) / span        # 0 at start -> 1 at frame bottom
    frac = min(max(frac, 0.0), 1.0)
    return nudge_max * frac


def band(label, area_ratio, bbox_bottom_norm, prev_tier=None, cfg=None):
    """Coarse distance tier for one detection: "near" or "far".

    Args:
        label:            COCO class string (e.g. "person", "car").
        area_ratio:       box area / frame area, 0..1. <= 0 -> degenerate -> far.
        bbox_bottom_norm: bottom edge of the box as a 0..1 fraction of frame
                          height (1.0 = frame bottom = on the ground in front).
        prev_tier:        last tier for THIS object ("near"/"far"/None). Drives
                          hysteresis; None (first sighting) uses the bare cutoff.
        cfg:              optional config object with .get(key, default) for
                          live threshold overrides (see module constants).

    Returns "near" or "far". Pure — no side effects, no clock.
    """
    # Degenerate / empty box: never claim it's near.
    if area_ratio <= 0:
        return "far"

    base = _threshold_for(label, cfg)
    # Ground nudge lowers the effective cutoff for boxes resting low in frame.
    effective = base * (1.0 - _ground_discount(bbox_bottom_norm, cfg))

    margin = HYSTERESIS_MARGIN
    if cfg is not None:
        margin = float(cfg.get("distance_hysteresis_margin", HYSTERESIS_MARGIN))

    # Separate enter/exit bands so a boundary-hovering object can't flap.
    enter = effective * (1.0 + margin)   # far -> near needs to clear this
    exit_ = effective * (1.0 - margin)   # near -> far needs to drop below this

    if prev_tier == "near":
        # Sticky near: only fall back to far on a clear drop.
        return "far" if area_ratio < exit_ else "near"
    if prev_tier == "far":
        # Sticky far: only rise to near on a clear gain.
        return "near" if area_ratio > enter else "far"

    # No prior tier (first sighting): bare threshold, no band.
    return "near" if area_ratio >= effective else "far"

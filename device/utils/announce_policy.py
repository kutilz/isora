"""
AnnouncePolicy — the single nav-speech gate (Decision 1A / E1A).

Pure decision function. Given the per-label memory of what was last announced,
the current frame's detections, and the clock, decide which objects to speak
NOW. This folds in the old `detection_gate` back-off: instead of "announce N
times then go quiet", it speaks on CHANGE and keeps a hazard audible on a timer.

Why a pure function (not a class): the decision is the part worth testing to
death, and a function with (state in -> decisions + next-state out) is trivially
unit-testable by feeding it frames. The caller (AudioManager) owns the state
dict and runs this on the single AI-loop thread, so no lock is needed.

    ┌─ force (on-demand readout) ───────────────────────► announce ALL current
    ├─ new label ──────────────────────────────────────► announce
    ├─ grid-cell changed ──────────────────────────────► announce
    ├─ distance-tier changed (far<->near) ─────────────► announce
    ├─ near/danger + unchanged + (now-last) >= remind ─► re-announce  (SAFETY)
    └─ else ───────────────────────────────────────────► suppress
A per-label cooldown spaces even legitimate changes; a per-tick cap stops a busy
scene reading out a paragraph. force bypasses both the cooldown and the cap.

State shape (held by the caller):
    { label: {"cell": str, "tier": str, "danger": bool, "last": float} }
decide() returns (announcements, new_state). new_state is built ONLY from labels
present this frame, so a disappeared object is pruned (its danger timer resets)
rather than re-announcing forever.

    detections (this frame)        state (last announced)
            │                              │
            ▼                              ▼
      rank danger/near first ──► per-label change/timer test ──► announcements
            │                                                        │
            └────────────► new_state (present labels only) ◄─────────┘
"""

# Defaults mirror config.py; kept here so the function is usable with cfg=None.
_DEFAULTS = {
    "announce_cooldown_s": 1.5,      # min spacing between announces of one label
    "announce_danger_remind_s": 3.0, # re-announce an unchanged near/danger object
    "announce_max_per_tick": 2,      # cap announces per frame (force ignores this)
}


def _get(cfg, key):
    if cfg is None:
        return _DEFAULTS[key]
    try:
        v = cfg.get(key, _DEFAULTS[key])
    except AttributeError:
        v = _DEFAULTS[key]
    return v if v is not None else _DEFAULTS[key]


def _is_danger(det) -> bool:
    """A detection is 'urgent' if flagged is_danger or it sits in the near tier."""
    return bool(det.get("is_danger")) or det.get("tier") == "near"


def decide(state, detections, now, cfg=None, force=False):
    """See module docstring. Returns (announcements, new_state).

    announcements: list of {"label","position","tier","is_danger"} to speak.
    new_state:     replacement state dict (caller persists it verbatim).
    """
    cooldown_s = float(_get(cfg, "announce_cooldown_s"))
    remind_s   = float(_get(cfg, "announce_danger_remind_s"))
    max_per    = int(_get(cfg, "announce_max_per_tick"))

    # Urgent (danger/near) first, then by confidence. Stable for ties.
    ranked = sorted(
        detections,
        key=lambda d: (_is_danger(d), d.get("confidence", 0.0)),
        reverse=True,
    )

    new_state = {}
    announcements = []
    spoken = 0

    for det in ranked:
        label = det.get("label")
        if not label or label in new_state:
            continue  # ignore unlabeled / keep the best (first) box per label

        cell   = det.get("position", "")
        tier   = det.get("tier", "far")
        danger = _is_danger(det)
        prev   = state.get(label)
        last   = prev["last"] if prev else 0.0

        # Decide whether this object earns a word this frame.
        if force:
            speak = True
        elif prev is None:
            speak = True                                   # new object
        elif cell != prev["cell"] or tier != prev["tier"]:
            speak = True                                   # moved cell or tier
        elif danger and (now - last) >= remind_s:
            speak = True                                   # hazard re-announce
        else:
            speak = False                                  # unchanged & calm

        # Cooldown + per-tick cap (force bypasses both).
        if speak and not force:
            if prev is not None and (now - last) < cooldown_s:
                speak = False
            elif spoken >= max_per:
                speak = False

        if speak:
            last = now
            announcements.append({
                "label": label, "position": cell,
                "tier": tier, "is_danger": danger,
            })
            spoken += 1

        new_state[label] = {"cell": cell, "tier": tier,
                            "danger": danger, "last": last}

    return announcements, new_state

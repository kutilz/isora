"""Detection-announce gate — stop a stuck/phantom detection from spamming.

Explorer mode re-runs YOLO every loop tick and asks to announce the top objects.
A covered or blurred lens can emit the *same* phantom box ("orang di depan")
indefinitely, and a flat 2 s cooldown then replays it forever — the "ngespam
gajelas" the user hit.

This is the pure decision layer (no clock, no audio): for each alert key it
announces normally a few times, then backs off to an occasional reminder until
the alert *changes* (different object/position = genuinely new info) or
disappears long enough to count as fresh again. Per-key state means several real
objects each get their own back-off independently.
"""


def decide_announce(states, key, now, cooldown_s=2.0, repeat_limit=3,
                    remind_s=30.0):
    """Should the alert `key` be spoken at time `now`? Mutates `states` in place.

    `states` maps key -> {"count", "last"}.
      - unseen key, or absent long enough to be "fresh" again -> announce, reset.
      - within the first `repeat_limit` announces -> announce, spaced by cooldown.
      - past the limit -> stay quiet until `remind_s` elapsed, then remind once.
    `repeat_limit <= 0` disables back-off (legacy: announce every cooldown).
    """
    st = states.get(key)
    # First sighting, or this key has been gone long enough to be "new" again.
    fresh_after = max(remind_s * 2.0, cooldown_s * 4.0)
    if st is None or (now - st["last"]) >= fresh_after:
        states[key] = {"count": 1, "last": now}
        return True

    capped = repeat_limit > 0 and st["count"] >= repeat_limit
    spacing = remind_s if capped else cooldown_s
    if now - st["last"] < spacing:
        return False

    # Allowed: don't grow the count past the cap (keeps reminders periodic).
    if not capped:
        st["count"] += 1
    st["last"] = now
    return True


def prune(states, now, max_age_s):
    """Drop keys not seen within `max_age_s` so `states` can't grow unbounded.
    Keys are few (label × position) but this keeps a long run tidy."""
    stale = [k for k, st in states.items() if now - st["last"] > max_age_s]
    for k in stale:
        del states[k]
    return states

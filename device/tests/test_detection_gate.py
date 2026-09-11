"""Detection back-off gate: a stuck/phantom alert announces a few times then
goes quiet (only an occasional reminder) until it changes — so the device can't
get stuck spamming "orang di depan". Pure logic, driven by an explicit clock.
"""

from utils.detection_gate import decide_announce, prune


KEY = "obj_person_center"


def test_new_key_always_announces():
    states = {}
    assert decide_announce(states, KEY, now=0.0) is True
    assert states[KEY]["count"] == 1


def test_same_key_is_spaced_by_cooldown():
    states = {}
    assert decide_announce(states, KEY, 0.0, cooldown_s=2.0) is True
    # too soon → suppressed
    assert decide_announce(states, KEY, 1.0, cooldown_s=2.0) is False
    # after cooldown → announces again
    assert decide_announce(states, KEY, 2.0, cooldown_s=2.0) is True


def test_backs_off_to_reminder_after_repeat_limit():
    states = {}
    t = 0.0
    # 3 announces (limit=3), each spaced by cooldown=2s
    for i in range(3):
        assert decide_announce(states, KEY, t, cooldown_s=2.0, repeat_limit=3, remind_s=30.0) is True
        t += 2.0
    # now capped: cooldown-spacing no longer enough — must wait the long remind
    assert decide_announce(states, KEY, t, cooldown_s=2.0, repeat_limit=3, remind_s=30.0) is False
    t += 2.0
    assert decide_announce(states, KEY, t, cooldown_s=2.0, repeat_limit=3, remind_s=30.0) is False
    # after remind_s from the last announce → one reminder, then quiet again
    assert decide_announce(states, KEY, 4.0 + 30.0, cooldown_s=2.0, repeat_limit=3, remind_s=30.0) is True
    assert decide_announce(states, KEY, 4.0 + 31.0, cooldown_s=2.0, repeat_limit=3, remind_s=30.0) is False


def test_changed_key_is_fresh_info_and_announces():
    states = {}
    assert decide_announce(states, "obj_person_center", 0.0) is True
    # a different object/position is new info → announce immediately
    assert decide_announce(states, "obj_chair_left", 0.1) is True


def test_long_absence_resets_to_fresh():
    states = {}
    assert decide_announce(states, KEY, 0.0, cooldown_s=2.0, remind_s=30.0) is True
    # gone for well over the fresh-again window → treated as new, count resets
    assert decide_announce(states, KEY, 200.0, cooldown_s=2.0, remind_s=30.0) is True
    assert states[KEY]["count"] == 1


def test_repeat_limit_zero_disables_backoff():
    states = {}
    t = 0.0
    # With back-off off, it just obeys the base cooldown forever (no quieting).
    for _ in range(10):
        assert decide_announce(states, KEY, t, cooldown_s=2.0, repeat_limit=0) is True
        t += 2.0


def test_prune_drops_stale_keys():
    states = {"a": {"count": 1, "last": 0.0}, "b": {"count": 1, "last": 90.0}}
    prune(states, now=100.0, max_age_s=30.0)
    assert "a" not in states and "b" in states

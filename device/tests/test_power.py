"""Power governor: temperature and activity → a work budget the AI loop obeys.

The device is worn by someone walking. It cannot ask its user to "please turn
me off, I am hot" — the only honest response to heat is to do less work itself.
So the governor's whole contract is: given a temperature, say how much work is
allowed. Nothing here speaks, and nothing here touches hardware.
"""

import pytest

from utils.power import PowerGovernor


def test_cool_device_gets_the_full_work_budget():
    gov = PowerGovernor(full_fps=30, hot_c=80.0)
    plan = gov.update(temp_c=45.0)
    assert plan.tier == "normal"
    assert plan.target_fps == 30
    assert plan.preview is True


def test_crossing_the_hot_threshold_cuts_the_work_budget():
    gov = PowerGovernor(full_fps=30, hot_c=80.0)
    gov.update(temp_c=45.0)
    plan = gov.update(temp_c=81.0)
    # Less work per second, and the frame the web preview costs is the first
    # thing dropped — nobody is watching the dashboard while walking.
    assert plan.tier == "hot"
    assert plan.target_fps < 30
    assert plan.preview is False


def test_a_temperature_hovering_at_the_threshold_does_not_flap():
    # Flapping is worse than staying throttled: every downshift/upshift retimes
    # the loop, and an fps that oscillates makes detection streaks unstable.
    gov = PowerGovernor(full_fps=30, hot_c=80.0, recover_margin_c=5.0)
    assert gov.update(temp_c=81.0).tier == "hot"
    assert gov.update(temp_c=79.0).tier == "hot"      # dipped, but not cooled
    assert gov.update(temp_c=76.0).tier == "hot"
    assert gov.update(temp_c=74.9).tier != "hot"      # cooled past the margin


def test_an_unreadable_sensor_never_changes_the_plan():
    # get_health() reports 0.0 when /sys/class/thermal is empty. Treating that
    # as "ice cold" would slam a genuinely hot device back to full speed.
    gov = PowerGovernor(full_fps=30, hot_c=80.0)
    assert gov.update(temp_c=81.0).tier == "hot"
    for unreadable in (None, 0.0, -1.0, float("nan")):
        assert gov.update(temp_c=unreadable).tier == "hot"


def test_the_device_eases_off_before_it_is_hot():
    # Reacting only at the throttle point means the device races to 80C and
    # then slams. Shedding a little work early is what keeps it off the ceiling.
    gov = PowerGovernor(full_fps=30, hot_c=80.0)
    plan = gov.update(temp_c=74.0)
    assert plan.tier == "warm"
    assert plan.target_fps < 30
    assert plan.preview is True      # a warm device is still fully usable


def test_critical_heat_spends_the_least_it_can_while_still_navigating():
    gov = PowerGovernor(full_fps=30, hot_c=80.0)
    hot      = gov.update(temp_c=81.0)
    critical = gov.update(temp_c=92.0)
    assert critical.tier == "critical"
    assert 0 < critical.target_fps < hot.target_fps
    assert critical.preview is False


def test_the_plan_converts_into_the_sleep_the_loop_owes():
    # The old throttle wrote camera_fps and nothing read it, so "throttling"
    # changed no work at all. A plan is only real if it produces idle time.
    from utils.power import pace_delay

    gov  = PowerGovernor(full_fps=30, hot_c=80.0)
    fast = gov.update(temp_c=45.0)
    assert pace_delay(fast, elapsed_s=0.005) == pytest.approx(1 / 30 - 0.005, abs=1e-6)

    slow = gov.update(temp_c=92.0)                 # critical: 2 fps
    assert pace_delay(slow, elapsed_s=0.005) == pytest.approx(0.5 - 0.005, abs=1e-6)


def test_a_tick_that_overran_its_budget_sleeps_zero_not_negative():
    from utils.power import pace_delay

    plan = PowerGovernor(full_fps=30).update(temp_c=45.0)
    assert pace_delay(plan, elapsed_s=0.9) == 0.0


def test_a_quiet_scene_costs_less_and_wakes_instantly():
    # A helper standing still had the device running the full pipeline flat out
    # for nothing. Quiet time is cheap; the wake-up must not be, because the
    # thing that ends the quiet is exactly what the user needs to hear about.
    gov = PowerGovernor(full_fps=30, hot_c=80.0, idle_after_s=20.0, idle_fps=8.0)

    assert gov.update(temp_c=45.0, now=0.0,  busy=True).target_fps == 30
    assert gov.update(temp_c=45.0, now=10.0, busy=False).target_fps == 30   # too soon
    assert gov.update(temp_c=45.0, now=25.0, busy=False).target_fps == 8    # settled
    assert gov.update(temp_c=45.0, now=26.0, busy=True).target_fps == 30    # instant


def test_idling_can_only_lower_the_rate_never_raise_it():
    # idle_fps sits above the hot tier's budget on purpose here: going quiet
    # while hot must not hand back frames the heat already took away.
    gov = PowerGovernor(full_fps=30, hot_c=80.0, idle_after_s=20.0, idle_fps=8.0)
    gov.update(temp_c=81.0, now=0.0, busy=True)
    hot_busy = gov.update(temp_c=81.0, now=1.0, busy=True)
    hot_idle = gov.update(temp_c=81.0, now=30.0, busy=False)
    assert hot_busy.target_fps == 6
    assert hot_idle.target_fps == 6

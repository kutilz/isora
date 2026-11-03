"""The spoken "still working" cues during a cloud call must inform, not nag."""

from core.ai_engine import AIEngine, _ProgressCues


def run(duration_s, slow_after_s=12.0, tick_s=3.0, drift_s=0.0):
    cues = _ProgressCues(slow_after_s)
    said = []
    t = tick_s
    while t <= duration_s:
        cue = cues.next(t + drift_s)
        if cue:
            said.append((t, cue))
        t += tick_s
    return said


def test_a_normal_call_never_mentions_the_connection():
    assert run(10) == [(3.0, "masih_memproses"), (9.0, "masih_memproses")]


def test_slow_connection_is_said_only_once_however_long_it_takes():
    # The complaint: on a 24 s call it repeated every 3 s, a dozen plays in 15 min.
    said = [cue for _, cue in run(60)]
    assert said.count("koneksi_lambat") == 1


def test_a_long_call_still_shows_it_is_alive():
    # A blind user cannot see that the device has not hung.
    assert run(40) == [
        (3.0, "masih_memproses"),
        (9.0, "masih_memproses"),
        (12.0, "koneksi_lambat"),
        (21.0, "masih_memproses"),
        (30.0, "masih_memproses"),
        (39.0, "masih_memproses"),
    ]


def _failure_cue(said_slow):
    engine = AIEngine.__new__(AIEngine)
    engine._said_slow = said_slow
    return engine._failure_cue(TimeoutError("The read operation timed out"),
                               "gagal_menganalisis")


def test_a_timeout_after_the_slow_cue_says_the_attempt_failed():
    # 3 Nov 2026: "koneksi lambat" at 12 s and again at the 15 s timeout, so the
    # user heard more waiting when the attempt was already over.
    assert _failure_cue(said_slow=True) == "gagal_menganalisis"


def test_a_timeout_before_the_slow_cue_still_names_the_connection():
    # Mode PIMNAS times out at 10 s, before the slow cue has had its turn.
    assert _failure_cue(said_slow=False) == "koneksi_lambat"


def test_tick_drift_does_not_skip_a_cue():
    assert [c for _, c in run(9, drift_s=0.05)] == ["masih_memproses", "masih_memproses"]
    cues = _ProgressCues(12.0)
    assert cues.next(3.2) == "masih_memproses"
    assert cues.next(6.2) is None
    assert cues.next(8.99) == "masih_memproses"   # 5.79 s later: still counts

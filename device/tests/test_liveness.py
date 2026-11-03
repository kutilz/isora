"""utils/liveness.py - the heartbeat system/supervise.sh judges the app by."""

from utils.liveness import LivenessBeacon, mark_stopping


def test_beats_while_the_loop_is_healthy(tmp_path):
    p = tmp_path / "alive"
    b = LivenessBeacon(is_alive_fn=lambda: True, path=str(p),
                       uptime_fn=lambda: "1234.56")
    assert b.beat_once()
    assert p.read_text() == "1234.56\n"


def test_stops_beating_when_the_loop_goes_stale(tmp_path):
    p = tmp_path / "alive"
    healthy = [True]
    up = ["100.00"]
    b = LivenessBeacon(is_alive_fn=lambda: healthy[0], path=str(p),
                       uptime_fn=lambda: up[0])
    b.beat_once()
    healthy[0] = False
    up[0] = "200.00"
    assert not b.beat_once()
    # The file keeps the last good beat, so it ages and the supervisor acts.
    assert p.read_text() == "100.00\n"


def test_a_probe_that_throws_does_not_count_as_a_wedge(tmp_path):
    def boom():
        raise RuntimeError("probe broke")
    b = LivenessBeacon(is_alive_fn=boom, path=str(tmp_path / "alive"),
                       uptime_fn=lambda: "1.0")
    assert b.beat_once()


def test_without_an_uptime_source_nothing_starts(tmp_path):
    b = LivenessBeacon(is_alive_fn=lambda: True, path=str(tmp_path / "alive"),
                       uptime_fn=lambda: None)
    assert b.start() is False
    assert not (tmp_path / "alive").exists()


def test_an_unwritable_path_never_raises(tmp_path):
    b = LivenessBeacon(is_alive_fn=lambda: True,
                       path=str(tmp_path / "missing-dir" / "alive"),
                       uptime_fn=lambda: "1.0")
    assert b.beat_once() is False


def test_mark_stopping(tmp_path):
    p = tmp_path / "stopping"
    assert mark_stopping(str(p))
    assert p.exists()
    assert mark_stopping(str(tmp_path / "nope" / "stopping")) is False

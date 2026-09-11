"""StageTimer — per-stage latency instrumentation for the context-mode pipeline.

These tests pin the *behaviour* we need to stop guessing where context-mode
latency goes: record how long each named stage took, total it, and name the
dominant stage. A fake clock keeps the tests deterministic (no real sleeping).
"""

from utils.stage_timer import StageTimer


class FakeClock:
    """Deterministic monotonic clock; advance() simulates elapsed seconds."""

    def __init__(self):
        self.now = 1000.0  # arbitrary non-zero start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def test_records_each_stage_total_and_dominant():
    clk = FakeClock()
    t = StageTimer(clock=clk)

    with t.stage("gemini"):
        clk.advance(7.0)
    with t.stage("tts_first"):
        clk.advance(1.8)

    s = t.summary()
    assert s["gemini_ms"] == 7000
    assert s["tts_first_ms"] == 1800
    assert s["total_ms"] == 8800
    assert s["dominant"] == "gemini"


def test_oneline_lists_stages_worst_first():
    clk = FakeClock()
    t = StageTimer(clock=clk)

    with t.stage("tts_first"):
        clk.advance(1.8)
    with t.stage("gemini"):          # recorded second, but it's the worst
        clk.advance(7.0)

    # Header carries total + dominant; stages sorted by cost descending so the
    # bottleneck is the first thing you read in the device log.
    assert t.oneline() == (
        "total=8800ms dominant=gemini | gemini=7000ms tts_first=1800ms"
    )

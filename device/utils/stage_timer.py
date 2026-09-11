"""StageTimer — lightweight per-stage latency instrumentation.

The context-mode pipeline (Gemini Vision → gTTS synth → streamed playback) is
network-bound and its cost was being *guessed* at. StageTimer makes it
measurable: wrap each stage in `with timer.stage("name"):` and `summary()`
returns each stage's milliseconds, the total, and which stage dominated — so a
single log line tells us exactly where a slow capture spent its time.

Pure and dependency-free (clock is injectable) so it unit-tests deterministically
and adds negligible overhead on the device.
"""

import time
from contextlib import contextmanager


class StageTimer:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._durations = {}   # stage name -> seconds (insertion-ordered)

    @contextmanager
    def stage(self, name):
        start = self._clock()
        try:
            yield
        finally:
            self._durations[name] = self._clock() - start

    def summary(self):
        """Return {<stage>_ms: int, total_ms: int, dominant: str}."""
        out = {}
        total = 0.0
        dominant = None
        dominant_s = -1.0
        for name, secs in self._durations.items():
            out[f"{name}_ms"] = round(secs * 1000)
            total += secs
            if secs > dominant_s:
                dominant_s = secs
                dominant = name
        out["total_ms"] = round(total * 1000)
        out["dominant"] = dominant
        return out

    def oneline(self):
        """Compact single-line log form, stages sorted worst-first."""
        stages = sorted(self._durations.items(), key=lambda kv: kv[1], reverse=True)
        body = " ".join(f"{name}={round(secs * 1000)}ms" for name, secs in stages)
        s = self.summary()
        return f"total={s['total_ms']}ms dominant={s['dominant']} | {body}"

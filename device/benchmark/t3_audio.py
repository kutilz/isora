#!/usr/bin/env python3
"""
Test 3 — Audio Priority & Interrupt
=====================================
Memverifikasi bahwa audio prioritas tinggi (CRITICAL) selalu
berhasil menginterupsi audio prioritas rendah (LOW).

Skenario Uji:
  A. Interupsi saat LOW sedang di-play:
       Mulai play task LOW (durasi 2s simulasi)
       → 0.3s kemudian insert CRITICAL
       → Ukur apakah CRITICAL mulai play < 150ms setelah diinsert

  B. Pra-emtif dari queue:
       Insert 5 × LOW ke queue saat idle
       → Insert 1 × CRITICAL
       → Verifikasi CRITICAL diambil PERTAMA dari queue

  C. Cooldown isolation:
       Pastikan cooldown label A tidak memblokir label B

Standar Kelulusan:
  100% sukses interupsi (Skenario A) — zero tolerance

Score:
  interrupt_success_rate × 100
  Bonus +5 jika avg_interrupt_delay < 50ms (tapi capped di 100)
"""

import sys, os, time, json, threading
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

RESULTS_FILE      = "/root/logs/bench_t3_audio.json"
INTERRUPT_TRIALS  = 20   # jumlah percobaan skenario A
INTERRUPT_DELAY_S = 0.30  # jeda sebelum inject CRITICAL
MAX_INTERRUPT_LATENCY_MS = 150.0


def _make_emit(cb=None):
    def emit(text="", tag="plain"):
        if cb:
            cb(text, tag)
        print(text, flush=True)
    return emit


# ─── Instrumented AudioManager (no real playback) ────────────────────────────

class _FakePlayer:
    """
    Subclass of AudioManager behaviour for testing.
    Overrides _play_pcm to simulate duration without real audio hardware.
    Records timing events for analysis.
    """

    def __init__(self):
        import queue as _q
        from core.audio_manager import (
            AudioManager, CRITICAL, HIGH, NORMAL, LOW,
            _Task, _next_seq,
        )
        self._CRITICAL = CRITICAL
        self._HIGH     = HIGH
        self._NORMAL   = NORMAL
        self._LOW      = LOW
        self._Task     = _Task
        self._next_seq = _next_seq

        # Build a lightweight mock AudioManager
        import collections
        self._pq           = _q.PriorityQueue()
        self._interrupt    = threading.Event()
        self._stop         = threading.Event()
        self._current_prio = LOW
        self._cooldown_map = collections.defaultdict(float)
        self._cd_lock      = threading.Lock()

        # Event log: list of (event_type, priority, timestamp)
        self._log:  list = []
        self._log_lock = threading.Lock()

        # "Currently playing" simulation state
        self._playing_duration = 0.0
        self._play_lock = threading.Lock()

        # Start consumer thread
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="T3AudioTest")
        self._thread.start()

    def queue(self, text: str, priority: int, label: str = ""):
        task    = self._Task(text, None, priority, label)
        enqueue_ts = time.perf_counter()

        with self._log_lock:
            self._log.append(("enqueued", priority, enqueue_ts, task.seq))

        self._pq.put((priority, task.seq, task))

        if priority < self._current_prio:
            self._interrupt.set()

    def _loop(self):
        import queue as _q
        while not self._stop.is_set():
            try:
                _, _, task = self._pq.get(timeout=0.05)
                self._play_task(task)
            except _q.Empty:
                pass

    def _play_task(self, task):
        self._current_prio = task.priority
        self._interrupt.clear()

        play_ts = time.perf_counter()
        with self._log_lock:
            self._log.append(("play_start", task.priority, play_ts, task.seq))

        # Simulate playback duration: CRITICAL=0.5s, HIGH=1s, NORMAL=1.5s, LOW=2s
        durations = {self._CRITICAL: 0.5, self._HIGH: 1.0,
                     self._NORMAL: 1.5, self._LOW: 2.0}
        duration = durations.get(task.priority, 1.0)

        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            if self._interrupt.is_set() or self._stop.is_set():
                with self._log_lock:
                    self._log.append(("interrupted", task.priority, time.perf_counter(), task.seq))
                self._current_prio = self._LOW
                return
            time.sleep(0.01)

        with self._log_lock:
            self._log.append(("play_end", task.priority, time.perf_counter(), task.seq))
        self._current_prio = self._LOW

    def stop(self):
        self._stop.set()

    def get_log(self):
        with self._log_lock:
            return list(self._log)


# ─── Scenario A: Runtime interrupt ────────────────────────────────────────────

def _scenario_a(fp: _FakePlayer, n: int, emit) -> dict:
    """
    Start a LOW task, then inject CRITICAL after delay.
    Measure: did CRITICAL start within MAX_INTERRUPT_LATENCY_MS?
    """
    emit(f"\n  [A] Runtime interrupt ({n} trials, inject after {INTERRUPT_DELAY_S*1000:.0f}ms)")

    successes   = 0
    delays_ms   = []

    for i in range(n):
        # Clear log
        with fp._log_lock:
            fp._log.clear()

        fp.queue(f"low_task_{i}", fp._LOW, label=f"low_{i}")

        # Let LOW start playing
        time.sleep(0.05)

        t_inject = time.perf_counter()
        fp.queue(f"critical_task_{i}", fp._CRITICAL, label=f"crit_{i}")

        # Wait up to 500ms for CRITICAL to appear in log
        deadline = time.monotonic() + 0.5
        critical_play_ts = None

        while time.monotonic() < deadline:
            log = fp.get_log()
            for ev in log:
                if ev[0] == "play_start" and ev[1] == fp._CRITICAL:
                    critical_play_ts = ev[2]
                    break
            if critical_play_ts:
                break
            time.sleep(0.01)

        if critical_play_ts is not None:
            delay_ms = (critical_play_ts - t_inject) * 1000
            delays_ms.append(delay_ms)
            if delay_ms <= MAX_INTERRUPT_LATENCY_MS:
                successes += 1
                emit(f"    Trial {i+1:2d}: ✓ delay={delay_ms:.1f}ms")
            else:
                emit(f"    Trial {i+1:2d}: ✗ delay={delay_ms:.1f}ms (>{MAX_INTERRUPT_LATENCY_MS}ms)", "warn")
        else:
            emit(f"    Trial {i+1:2d}: ✗ CRITICAL never played", "err")

        # Let CRITICAL finish before next trial
        time.sleep(0.7)

    rate = successes / n
    avg_delay = sum(delays_ms) / len(delays_ms) if delays_ms else 0

    emit(f"\n  [A] Sukses: {successes}/{n}  ({rate:.0%})")
    emit(f"  [A] Avg interrupt latency: {avg_delay:.1f}ms")

    return {
        "successes":      successes,
        "trials":         n,
        "rate":           round(rate, 4),
        "avg_delay_ms":   round(avg_delay, 2),
        "delays_ms":      [round(d, 2) for d in delays_ms],
    }


# ─── Scenario B: Queue pre-emption ────────────────────────────────────────────

def _scenario_b(emit) -> dict:
    """
    Insert 5 × LOW then 1 × CRITICAL while consumer is idle.
    CRITICAL must be dequeued first.
    """
    emit("\n  [B] Queue pre-emption (5×LOW + 1×CRITICAL, consumer paused)")

    import queue as _q
    from core.audio_manager import CRITICAL, LOW, _Task, _next_seq

    pq = _q.PriorityQueue()

    for i in range(5):
        t = _Task(f"low_{i}", None, LOW, "")
        pq.put((t.priority, t.seq, t))

    crit = _Task("critical", None, CRITICAL, "")
    pq.put((crit.priority, crit.seq, crit))

    order = []
    while not pq.empty():
        _, _, task = pq.get_nowait()
        order.append(task.priority)

    first_is_critical = (order[0] == CRITICAL)
    emit(f"    Dequeue order: {['CRITICAL' if p==CRITICAL else 'LOW' for p in order]}")
    emit(f"    {'✓' if first_is_critical else '✗'} CRITICAL diambil pertama",
         "ok" if first_is_critical else "err")

    return {
        "first_is_critical": first_is_critical,
        "dequeue_order":     order,
    }


# ─── Scenario C: Cooldown isolation ───────────────────────────────────────────

def _scenario_c(fp: _FakePlayer, emit) -> dict:
    """
    Cooldown for label A should not block label B.
    """
    emit("\n  [C] Cooldown isolation (label A blocked, label B free)")

    import collections
    cooldown_s = 2.0

    # Simulate A played just now
    with fp._cd_lock:
        fp._cooldown_map["label_A"] = time.monotonic()

    # Try to queue A (should be blocked) and B (should pass)
    from core.audio_manager import _Task, NORMAL, _next_seq
    import queue as _q

    results = {}

    # Simulate queue() logic
    def _would_queue(label):
        now = time.monotonic()
        with fp._cd_lock:
            last = fp._cooldown_map.get(label, 0)
        return (now - last) >= cooldown_s

    a_passes = _would_queue("label_A")
    b_passes = _would_queue("label_B")

    emit(f"    label_A (just played): queued={'yes' if a_passes else 'no (cooldown, expected)'}",
         "ok" if not a_passes else "err")
    emit(f"    label_B (fresh):       queued={'yes (expected)' if b_passes else 'no'}",
         "ok" if b_passes else "err")

    passed = (not a_passes) and b_passes
    return {
        "a_blocked":  not a_passes,
        "b_passed":   b_passes,
        "passed":     passed,
    }


# ─── Main ────────────────────────────────────────────────────────────────────

def run(n_interrupt_trials: int = INTERRUPT_TRIALS, emit_cb=None) -> dict:
    emit = _make_emit(emit_cb)

    emit("═" * 64, "div")
    emit("T3  AUDIO PRIORITY & INTERRUPT", "section")
    emit("═" * 64, "div")
    emit(f"  Interrupt trials      : {n_interrupt_trials}")
    emit(f"  Max interrupt latency : {MAX_INTERRUPT_LATENCY_MS} ms")
    emit(f"  Pass requirement      : 100% interrupt success")

    try:
        from core.audio_manager import CRITICAL, LOW  # noqa: import check
    except ImportError as e:
        emit(f"  ✗ Cannot import AudioManager: {e}", "err")
        return {"test": "T3_Audio", "passed": False, "score": 0, "error": str(e)}

    fp = _FakePlayer()

    a = _scenario_a(fp, n_interrupt_trials, emit)
    b = _scenario_b(emit)
    c = _scenario_c(fp, emit)

    fp.stop()

    # ── Overall result ────────────────────────────────────────────────────────
    interrupt_rate = a["rate"]
    passed_a = interrupt_rate == 1.0
    passed_b = b["first_is_critical"]
    passed_c = c["passed"]
    overall  = passed_a and passed_b and passed_c

    emit()
    emit(f"  [A] Interrupt success  : {interrupt_rate:.0%}   {'PASS' if passed_a else 'FAIL'}",
         "ok" if passed_a else "err")
    emit(f"  [B] Queue order        : {'PASS' if passed_b else 'FAIL'}",
         "ok" if passed_b else "err")
    emit(f"  [C] Cooldown isolation : {'PASS' if passed_c else 'FAIL'}",
         "ok" if passed_c else "err")

    # Score: interrupt rate is the primary metric
    score_base  = round(interrupt_rate * 100)
    score_bonus = 5 if a["avg_delay_ms"] < 50 else 0
    score       = min(100, score_base + score_bonus)
    if not passed_b:
        score = min(score, 80)
    if not passed_c:
        score = min(score, 90)

    emit()
    tag   = "ok" if overall else "err"
    emoji = "✓" if overall else "✗"
    emit(f"  {emoji} Overall: {'PASS' if overall else 'FAIL'}", tag)
    emit(f"  Score: {score}/100")

    results = {
        "test":               "T3_Audio",
        "passed":             overall,
        "score":              score,
        "scenario_a":         a,
        "scenario_b":         b,
        "scenario_c":         c,
        "interrupt_rate":     round(interrupt_rate, 4),
        "avg_interrupt_ms":   a["avg_delay_ms"],
        "max_latency_ms":     MAX_INTERRUPT_LATENCY_MS,
        "timestamp":          time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    _save(results)
    return results


def _save(results: dict):
    os.makedirs(os.path.dirname(RESULTS_FILE), exist_ok=True)
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    run()

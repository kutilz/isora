"""SceneMetrics records context-mode describe latency for the /buttons dashboard.

The AI thread opens a record after Gemini and notes the render plan; the audio
thread fills timing in later, matched by id. These tests pin that contract with a
fixed clock so they're deterministic and hardware-free.
"""

from utils.scene_metrics import SceneMetrics


def _fixed_iso():
    return "2026-06-16T21:00:00"


def test_start_describe_surfaces_gemini_in_last_immediately():
    m = SceneMetrics(now_iso=_fixed_iso)
    sid = m.start_describe("Kasur di kiri, pintu di depan.", "sedang", 5300.4)
    snap = m.snapshot()
    assert snap["last"]["id"] == sid
    assert snap["last"]["gemini_ms"] == 5300          # rounded
    assert snap["last"]["verbosity"] == "sedang"
    # audio phase not in yet
    assert snap["last"]["audio_source"] is None
    assert snap["last"]["to_audio_ms"] is None


def test_cache_hit_path_records_instant_audio_start():
    m = SceneMetrics(now_iso=_fixed_iso)
    sid = m.start_describe("Kasur di kiri.", "sedang", 5000)
    m.note_plan(sid, "cache", words=3, cached_words=3)
    m.note_cache_audio(sid, audio_ms=1400, assemble_ms=4)
    last = m.snapshot()["last"]
    assert last["audio_source"] == "cache"
    assert last["words"] == 3 and last["cached_words"] == 3
    assert last["audio_ms"] == 1400
    assert last["to_audio_ms"] == 4                   # near-instant
    assert last["synth_ms"] is None


def test_synth_path_records_gtts_time_as_to_audio():
    m = SceneMetrics(now_iso=_fixed_iso)
    sid = m.start_describe("Ada gantungan baju di dinding.", "detail", 6100)
    m.note_plan(sid, "synth", words=5, cached_words=2)
    m.note_synth(sid, synth_ms=2300, audio_ms=2600)
    last = m.snapshot()["last"]
    assert last["audio_source"] == "synth"
    assert last["synth_ms"] == 2300
    assert last["to_audio_ms"] == 2300                # synth precedes audio
    assert last["audio_ms"] == 2600


def test_late_update_with_wrong_id_does_not_corrupt_current_record():
    # A stray synth (e.g. a QRIS info clip) on the play loop carries no/old id;
    # it must not overwrite the in-flight describe's timing.
    m = SceneMetrics(now_iso=_fixed_iso)
    sid = m.start_describe("Kasur di kiri.", "sedang", 5000)
    m.note_plan(sid, "cache", words=3, cached_words=3)
    m.note_cache_audio(sid, audio_ms=1400, assemble_ms=4)
    m.note_synth(scene_id=999999, synth_ms=8000, audio_ms=9000)   # not our id
    last = m.snapshot()["last"]
    assert last["audio_source"] == "cache"
    assert last["to_audio_ms"] == 4                   # unchanged
    assert last["synth_ms"] is None


def test_summary_reports_hit_rate_and_averages():
    m = SceneMetrics(now_iso=_fixed_iso)
    s1 = m.start_describe("a", "sedang", 5000)
    m.note_plan(s1, "cache", 3, 3); m.note_cache_audio(s1, 1000, 2)
    s2 = m.start_describe("b", "sedang", 7000)
    m.note_plan(s2, "synth", 4, 1); m.note_synth(s2, 3000, 3200)
    summary = m.snapshot()["summary"]
    assert summary["count"] == 2
    assert summary["avg_gemini_ms"] == 6000           # (5000+7000)/2
    assert summary["cache_hits"] == 1
    assert summary["synth_count"] == 1
    assert summary["hit_rate"] == 0.5
    assert summary["avg_cache_to_audio_ms"] == 2
    assert summary["avg_synth_to_audio_ms"] == 3000


def test_empty_summary_is_safe():
    m = SceneMetrics(now_iso=_fixed_iso)
    snap = m.snapshot()
    assert snap["last"] is None
    assert snap["summary"] == {"count": 0}
    assert snap["history"] == []

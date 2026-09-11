"""SceneMetrics — recent context-mode describe latency, for the /buttons dashboard.

A "describe" is two stages: the Gemini vision round-trip, then rendering audio.
Audio renders one of two ways:
  - "cache" — every word was already in the per-word cache, so the clip is
    concatenated from cached audio with ZERO network (near-instant), or
  - "synth" — a word was missing (or caching is off, i.e. "satu blok audio"
    mode), so the whole sentence is spoken via one gTTS call.

This records, per describe, where the time went and how the audio was rendered,
so the operator can compare "caching per-kata" vs "satu blok audio" by eye
instead of guessing.

Thread-safety: the AI loop thread opens a record (start_describe) and notes the
render plan (note_plan); the audio playback thread fills in the timing later
(note_synth on the synth path, note_cache_audio on the cache path). Every
mutation is under one lock. Describes are user-paced and sequential on this
single-core device, and each late audio-phase update is matched to its describe
by id — so a stray QRIS/info synth on the play loop can never corrupt a scene
record it doesn't own.

Pure and clock-injectable so it unit-tests deterministically with no hardware.
"""

import threading
import time
from collections import deque

_MAX_HISTORY = 30


def _default_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


class SceneMetrics:
    def __init__(self, now_iso=_default_iso):
        self._now_iso = now_iso
        self._lock = threading.Lock()
        self._seq = 0
        self._last = None
        self._history = deque(maxlen=_MAX_HISTORY)

    # ─── Writers ──────────────────────────────────────────────────────────────

    def start_describe(self, text: str, verbosity: str, gemini_ms) -> int:
        """Open a new describe record (AI thread, right after the Gemini call).

        Returns the record id used to attribute the later audio-phase updates.
        """
        with self._lock:
            self._seq += 1
            rec = {
                "id":           self._seq,
                "ts":           self._now_iso(),
                "text":         (text or "")[:80],
                "verbosity":    verbosity or "detail",
                "gemini_ms":    int(round(gemini_ms or 0)),
                "audio_source": None,   # "cache" | "synth"
                "words":        None,   # total word tokens in the sentence
                "cached_words": None,   # tokens served from the cache
                "synth_ms":     None,   # whole-sentence gTTS time (synth path)
                "audio_ms":     None,   # spoken audio duration
                "to_audio_ms":  None,   # describe audio-render -> audio ready
            }
            self._last = rec
            self._history.append(rec)
            return self._seq

    def note_plan(self, scene_id: int, source: str, words: int, cached_words: int):
        """Record how the audio will be rendered (cache concat vs whole synth)."""
        with self._lock:
            rec = self._find(scene_id)
            if rec is None:
                return
            rec["audio_source"] = source
            rec["words"] = int(words)
            rec["cached_words"] = int(cached_words)

    def note_cache_audio(self, scene_id: int, audio_ms, assemble_ms=0):
        """Cache hit: audio assembled from cached words (near-instant start)."""
        with self._lock:
            rec = self._find(scene_id)
            if rec is None:
                return
            rec["audio_ms"] = int(round(audio_ms or 0))
            rec["to_audio_ms"] = int(round(assemble_ms or 0))

    def note_synth(self, scene_id: int, synth_ms, audio_ms):
        """Synth path: whole-sentence gTTS time precedes audio start."""
        with self._lock:
            rec = self._find(scene_id)
            if rec is None:
                return
            rec["synth_ms"] = int(round(synth_ms or 0))
            rec["audio_ms"] = int(round(audio_ms or 0))
            rec["to_audio_ms"] = int(round(synth_ms or 0))

    # ─── Reader ───────────────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        """JSON-safe view: the last describe, a rolling summary, recent history."""
        with self._lock:
            last = dict(self._last) if self._last else None
            history = [dict(r) for r in self._history]
        return {
            "last":    last,
            "summary": self._summary(history),
            "history": history[-10:],
        }

    # ─── Internals ────────────────────────────────────────────────────────────

    def _find(self, scene_id):
        """Locate a record by id. Fast-path the most recent; fall back to scan."""
        if self._last is not None and self._last["id"] == scene_id:
            return self._last
        for rec in reversed(self._history):
            if rec["id"] == scene_id:
                return rec
        return None

    @staticmethod
    def _summary(history) -> dict:
        n = len(history)
        if not n:
            return {"count": 0}

        def avg(xs):
            xs = [x for x in xs if x is not None]
            return int(round(sum(xs) / len(xs))) if xs else None

        cache_hits = [r for r in history if r.get("audio_source") == "cache"]
        synths     = [r for r in history if r.get("audio_source") == "synth"]
        return {
            "count":                 n,
            "avg_gemini_ms":         avg([r.get("gemini_ms") for r in history]),
            "cache_hits":            len(cache_hits),
            "synth_count":           len(synths),
            "hit_rate":              round(len(cache_hits) / n, 2),
            "avg_cache_to_audio_ms": avg([r.get("to_audio_ms") for r in cache_hits]),
            "avg_synth_to_audio_ms": avg([r.get("to_audio_ms") for r in synths]),
        }


# ─── Singleton ────────────────────────────────────────────────────────────────
# Shared by the AI loop thread (start_describe / note_plan) and the audio
# playback thread (note_synth / note_cache_audio); read by the web thread.
scene_metrics = SceneMetrics()

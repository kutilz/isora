"""
Audio Manager — Non-blocking priority queue playback.

Priority levels (lower number = higher priority):
  CRITICAL (0) — close-range obstacle / emergency
  HIGH     (1) — important detection
  NORMAL   (2) — regular detection / system event
  LOW      (3) — informational / scene description

A newly queued task at a higher priority than what is currently
playing will interrupt playback immediately.
"""

import os
import re
import time
import queue
import threading
from collections import defaultdict
from typing import Optional

from utils.word_cache import WordCache, plan_utterance, assemble_words, tokenize
from utils.scene_metrics import scene_metrics
from utils.detection_gate import decide_announce, prune
from utils.announce_policy import decide as _announce_decide

CRITICAL = 0
HIGH     = 1
NORMAL   = 2
LOW      = 3

# ── Object-alert mapping ──────────────────────────────────────────────────────
# Detections carry an English COCO label + an Indonesian grid position
# (from position_from_bbox: "atas", "kiri-atas", "tengah", …). The pre-recorded
# chimes are named obj_<englishlabel>_<englishposkey>.wav with Indonesian audio
# ("orang di atas"). These maps bridge the two so obstacle alerts play the
# instant offline chime instead of falling back to (slow, online) gTTS.
_LABEL_ID = {
    "person": "orang", "motorcycle": "motor", "car": "mobil", "bicycle": "sepeda",
    "bus": "bus", "truck": "truk", "dog": "anjing", "cat": "kucing",
    "chair": "kursi", "bottle": "botol", "handbag": "tas", "backpack": "ransel",
}
_POS_KEY = {
    "tengah": "center", "kiri": "left", "kanan": "right",
    "atas": "top", "bawah": "bottom",
    "kiri-atas": "top_left", "kanan-atas": "top_right",
    "kiri-bawah": "bottom_left", "kanan-bawah": "bottom_right",
}
_POS_PHRASE = {
    "left": "di sebelah kiri", "right": "di sebelah kanan", "center": "di depan",
    "top": "di atas", "bottom": "di bawah",
    "top_left": "di kiri atas", "top_right": "di kanan atas",
    "bottom_left": "di kiri bawah", "bottom_right": "di kanan bawah",
}

_PCM_RATE    = 48000
_PCM_BYTES_S = _PCM_RATE * 2   # s16le mono = 2 bytes/sample

# Small tail so the very end of an utterance isn't clipped before the next task.
_PLAY_TAIL_PAD_S = 0.15


def residual_playback_wait_s(pcm_nbytes: int, play_call_elapsed_s: float,
                             pad_s: float = _PLAY_TAIL_PAD_S) -> float:
    """How long to keep holding the playback slot AFTER player.play() returns.

    Audio length is pcm_nbytes / _PCM_BYTES_S. On builds where play() blocks
    until the clip finishes, play_call_elapsed_s already covers (most of) that,
    so the residual collapses to ~pad. On builds where play() returns instantly,
    play_call_elapsed_s≈0 and we wait the whole clip out ourselves. Never
    negative (a play() that overruns our estimate just means we're already done).
    """
    audio_s = pcm_nbytes / _PCM_BYTES_S
    return round(max(0.0, audio_s + pad_s - play_call_elapsed_s), 3)

# Monotonically increasing counter for stable ordering within same priority
_SEQ      = 0
_SEQ_LOCK = threading.Lock()


def _next_seq() -> int:
    global _SEQ
    with _SEQ_LOCK:
        _SEQ += 1
        return _SEQ


# Sentence boundary: a .!? followed by whitespace. Lets us speak a long answer
# one sentence at a time so the first words come out while the rest is still
# being synthesized (see AIEngine.trigger_scene_description streaming path).
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def split_sentences(text: str, max_chunks: int = 3) -> list:
    """Split `text` into at most `max_chunks` speakable sentence chunks.

    Near-empty / single-sentence input returns a one-element list. Over-splitting
    is avoided by merging the tail once max_chunks is reached, so we never spawn
    a long string of tiny gTTS calls on a one-core device.
    """
    text = (text or "").strip()
    if not text:
        return []
    parts = [p.strip() for p in _SENT_SPLIT.split(text) if p.strip()]
    if len(parts) <= 1:
        return [text]
    if len(parts) > max_chunks:
        head = parts[: max_chunks - 1]
        head.append(" ".join(parts[max_chunks - 1:]))
        parts = head
    return parts


class _Task:
    __slots__ = ("text", "wav_path", "priority", "label", "seq", "is_cue",
                 "pcm_bytes", "scene_id")

    def __init__(self, text: str, wav_path: Optional[str],
                 priority: int, label: str, is_cue: bool = False,
                 pcm_bytes: Optional[bytes] = None,
                 scene_id: Optional[int] = None):
        self.text      = text
        self.wav_path  = wav_path
        self.priority  = priority
        self.label     = label
        self.is_cue    = is_cue
        # Ready-to-play PCM (e.g. concatenated word-cache audio); when set,
        # playback skips WAV lookup / synthesis entirely.
        self.pcm_bytes = pcm_bytes
        # When set, this is a context-mode scene synth: the play loop records
        # its gTTS + audio timing into scene_metrics under this id.
        self.scene_id  = scene_id
        self.seq       = _next_seq()

    def __lt__(self, other: "_Task") -> bool:
        if self.priority != other.priority:
            return self.priority < other.priority
        return self.seq < other.seq


def _read_file_bytes(path: str) -> Optional[bytes]:
    """Read a file's bytes, or None on any error (used by word-cache concat)."""
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def _ensure_pcm_standalone(wav_path: str) -> Optional[str]:
    """Convert WAV → PCM s16le 48 kHz mono, cached next to source. Module-level
    twin of AudioManager._ensure_pcm for use before an AudioManager exists."""
    import subprocess
    pcm = os.path.splitext(wav_path)[0] + ".pcm"
    if os.path.exists(pcm):
        return pcm
    try:
        ret = subprocess.run(
            [
                "ffmpeg", "-v", "warning", "-y", "-i", wav_path,
                "-f", "s16le", "-acodec", "pcm_s16le",
                "-ar", str(_PCM_RATE), "-ac", "1", pcm,
            ],
            shell=False, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
        ).returncode
    except (OSError, subprocess.SubprocessError):
        return None
    return pcm if ret == 0 and os.path.exists(pcm) else None


def play_wav_blocking(wav_name: str, audio_dir: str = "/root/audio",
                      volume: int = 80) -> bool:
    """
    Play a single pre-recorded WAV synchronously via maix.audio.Player.

    Safe to call at the very start of boot — before AudioManager/AIEngine exist —
    so the device can announce "Isora menyala" the instant it powers on, with no
    dependency on the rest of the pipeline. The WAV is converted to PCM once
    (ffmpeg, cached as .pcm next to the source), so subsequent boots are instant.
    Missing file or any error → returns False without raising.
    """
    wav_path = os.path.join(audio_dir, wav_name)
    if not os.path.exists(wav_path):
        return False
    pcm = _ensure_pcm_standalone(wav_path)
    if not pcm:
        return False
    try:
        from maix import audio as maix_audio
    except ImportError:
        return False
    try:
        with open(pcm, "rb") as f:
            pcm_data = f.read()
        player = maix_audio.Player()
        try:
            player.volume(volume)
        except Exception:
            pass
        player.play(bytes(pcm_data))
        duration_s = len(pcm_data) / _PCM_BYTES_S + 0.15
        deadline = time.monotonic() + duration_s
        while time.monotonic() < deadline:
            time.sleep(0.02)
        return True
    except Exception:
        return False


class AudioManager:

    def __init__(self, orchestrator, logger):
        self.orch   = orchestrator
        self.logger = logger

        # Resolved at construction so they can't change mid-run unexpectedly
        try:
            from config import cfg as _cfg
            self._audio_dir  = _cfg.AUDIO_DIR
            self._cooldown_s = _cfg.AUDIO_COOLDOWN_S
        except Exception:
            self._audio_dir  = "/root/audio"
            self._cooldown_s = 2.0

        # Per-word TTS cache for context-mode scene descriptions.
        try:
            from config import cfg as _cfg
            self._word_cache = WordCache(_cfg.get("word_cache_dir",
                                                  "/root/audio/word_cache"))
        except Exception:
            self._word_cache = WordCache("/root/audio/word_cache")

        self._pq: queue.PriorityQueue = queue.PriorityQueue()

        # label → monotonic timestamp of last play
        self._cooldown_map: dict = defaultdict(float)
        self._cd_lock = threading.Lock()

        # Detection-announce back-off state (per alert key) — stops a stuck
        # phantom detection from spamming. Guarded by _cd_lock; written only
        # from the AI loop thread via queue_object.
        self._det_states: dict = {}
        self._det_prune_at = 0.0

        # AnnouncePolicy state (Decision 1A/E1A): per-label memory of what was
        # last announced. Owned here, mutated only from the AI-loop thread via
        # announce_detections(), so no extra lock is needed.
        self._announce_state: dict = {}

        # Tracks priority of whatever is playing right now
        self._current_priority = LOW
        # Text currently being played (exposed to status endpoint)
        self._current_text: str = ""
        # Last non-empty caption, persists after playback completes so the
        # companion dashboard can show the most recent thing the user heard.
        self._last_caption: dict = {"text": "", "time_iso": "", "priority": "low"}
        self._text_lock = threading.Lock()
        # Set to interrupt ongoing playback sleep loop
        self._interrupt = threading.Event()
        self._stop      = threading.Event()

        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="AudioMgr"
        )
        self._thread.start()

    # ─── Public API ───────────────────────────────────────────────────────────

    def queue(self, text: str, priority: int = NORMAL, label: str = "",
              cooldown: Optional[float] = None, wav_name: Optional[str] = None):
        """
        Add text to the playback queue.
        If priority is higher than current playback, interrupt immediately.

        wav_name: explicit pre-recorded WAV filename (in audio_dir) to play
        instead of deriving one from `text`. `text` is still used for the
        caption and as the TTS fallback if that file is missing.
        """
        cd = cooldown if cooldown is not None else self._cooldown_s

        if label and cd > 0:
            with self._cd_lock:
                if time.monotonic() - self._cooldown_map[label] < cd:
                    return

        wav = None
        if wav_name:
            cand = os.path.join(self._audio_dir, wav_name)
            if os.path.exists(cand):
                wav = cand
        if wav is None:
            wav = self._find_wav(text)
        task = _Task(text, wav, priority, label)
        self._pq.put((priority, task.seq, task))

        if priority < self._current_priority:
            self._interrupt.set()

    def queue_object(self, label: str, position: str, is_danger: bool = False):
        """
        Helper for detected objects. Danger → CRITICAL, otherwise HIGH.

        Plays the pre-recorded chime obj_<label>_<poskey>.wav ("orang di atas")
        instantly/offline; if missing, falls back to speaking the same
        Indonesian phrase via gTTS.

        A repeat back-off (see _detection_allowed) drops the same alert once it
        has been announced a few times, so a stuck/phantom detection can't loop
        "orang di depan" forever. The gate owns spacing, so we pass cooldown=0.
        """
        priority = CRITICAL if is_danger else HIGH
        poskey   = _POS_KEY.get(position, position)
        obj_id   = _LABEL_ID.get(label, label)
        phrase   = _POS_PHRASE.get(poskey, position)
        spoken   = f"{obj_id} {phrase}".strip()
        key      = f"obj_{label}_{poskey}"
        if not self._detection_allowed(key):
            return
        self.queue(
            text=spoken,
            priority=priority,
            label=key,
            cooldown=0,
            wav_name=f"obj_{label}_{poskey}.wav",
        )

    # ─── Event-driven nav announce (AnnouncePolicy — Decision 1A/E1A) ─────────

    @staticmethod
    def nav_wav_candidates(label: str, poskey: str, tier: str) -> list:
        """Ordered pre-rendered WAV candidates for a nav alert, best → fallback.

        Always offline-resolvable: tier-specific phrase, then the plain phrase
        (which also serves the far tier), then the generic per-direction phrase,
        so a missing file never means silence (Decision 4A). A final earcon
        fallback is handled by the caller.
        """
        return [
            f"obj_{label}_{poskey}_{tier}.wav",   # tier-specific (near = "...dekat")
            f"obj_{label}_{poskey}.wav",          # plain phrase (also serves far)
            f"objek_{poskey}.wav",                # generic "ada objek di <arah>"
        ]

    def announce_detections(self, detections: list, force: bool = False):
        """Run the single nav-speech gate over this frame's detections.

        Replaces the old "top-2 every tick + back-off" loop. The pure policy
        (utils/announce_policy) decides what changed, what's an approaching
        hazard to re-announce, or — with force=True — reads out the whole scene
        on demand. State lives here and is replaced each call, so a disappeared
        object prunes itself (no stale danger timer)."""
        try:
            from config import cfg as _cfg
        except Exception:
            _cfg = None
        now = time.monotonic()
        announcements, self._announce_state = _announce_decide(
            self._announce_state, detections or [], now, cfg=_cfg, force=force,
        )
        for a in announcements:
            self._queue_nav(a["label"], a["position"], a["tier"], a["is_danger"])

    def _queue_nav(self, label: str, position: str, tier: str, is_danger: bool):
        """Queue one nav alert from a pre-rendered WAV, with offline fallbacks.

        near/danger → CRITICAL (barges in); otherwise HIGH. The policy owns
        spacing, so cooldown=0 here."""
        poskey   = _POS_KEY.get(position, position)
        objid    = _LABEL_ID.get(label, label)
        phrase   = _POS_PHRASE.get(poskey, position)
        suffix   = " dekat" if tier == "near" else ""
        caption  = f"{objid} {phrase}{suffix}".strip()
        priority = CRITICAL if is_danger else HIGH

        for wav_name in self.nav_wav_candidates(label, poskey, tier):
            if os.path.exists(os.path.join(self._audio_dir, wav_name)):
                self.queue(text=caption, priority=priority,
                           label=f"nav_{label}_{poskey}", cooldown=0,
                           wav_name=wav_name)
                return
        # Nothing pre-rendered matched: last-resort earcon (never silence).
        self.queue_cue("chime_obstacle.wav", priority=priority,
                       label=f"nav_{label}_{poskey}")

    def _detection_allowed(self, key: str) -> bool:
        """Repeat back-off decision for a detection alert (anti-spam)."""
        try:
            from config import cfg as _cfg
            cooldown_s   = float(_cfg.get("audio_cooldown_s", 2.0))
            repeat_limit = int(_cfg.get("detection_repeat_limit", 3))
            remind_s     = float(_cfg.get("detection_repeat_remind_s", 30.0))
        except Exception:
            cooldown_s, repeat_limit, remind_s = 2.0, 3, 30.0
        now = time.monotonic()
        with self._cd_lock:
            if now >= self._det_prune_at:
                prune(self._det_states, now, max_age_s=max(remind_s * 4, 120.0))
                self._det_prune_at = now + 60.0
            return decide_announce(
                self._det_states, key, now,
                cooldown_s=cooldown_s, repeat_limit=repeat_limit,
                remind_s=remind_s,
            )

    def user_barge_in(self, cue_wav: str = "chime_press.wav"):
        """Flush queued + currently-playing audio and play an instant cue.

        Called the moment a user presses a button so their action never has to
        wait behind detection spam already in the queue — the press always
        "lands" immediately. The cue is CRITICAL so a detection re-queued in the
        same instant can't jump ahead of it. Missing cue file → just the flush.
        """
        self.clear()  # drop everything pending + interrupt current playback
        if cue_wav:
            self.queue_cue(cue_wav, priority=CRITICAL, label="user_press")

    def queue_system(self, event: str):
        """System events (mode switches, low battery, …).

        `event` is a cue KEY like "memindai_kode_pembayaran". Play its
        pre-recorded WAV if present; otherwise the TTS fallback must speak a
        readable phrase — the raw key's underscores get read aloud as "garis
        bawah". We pass the underscore→space phrase as the spoken text and the
        key-named WAV as wav_name; _find_wav re-underscores the phrase, so any
        existing `<event>.wav` / `system_<event>.wav` is still matched.
        """
        self.queue(
            event.replace("_", " "),
            priority=NORMAL,
            label=f"sys_{event}",
            wav_name=f"{event}.wav",
        )

    def queue_cue(self, wav_name: str, priority: int = HIGH,
                  label: Optional[str] = None):
        """
        Play a non-speech chime (button tick, success/error tone, …).

        Cues always play their pre-recorded tone regardless of the user's
        audio_mode ("speech"/"chime"/"both") — they're tactile/state feedback,
        not speech. Missing file → silently skipped (no TTS fallback).
        """
        cand = os.path.join(self._audio_dir, wav_name)
        if not os.path.exists(cand):
            self.logger.debug(f"[Cue missing] {wav_name}", module="AudioMgr")
            return
        task = _Task(wav_name, cand, priority, label or "", is_cue=True)
        self._pq.put((priority, task.seq, task))
        if priority < self._current_priority:
            self._interrupt.set()

    def queue_info(self, text: str):
        """Low-priority informational audio (scene description, etc.)."""
        self.queue(text, priority=LOW)

    def warm_tts(self, text: str) -> bool:
        """Pre-synthesize gTTS + PCM for `text` into the cache *now*.

        Call this from the AI thread while a progress cue ("masih memproses")
        is still audible: the ~1.8 s gTTS network round-trip then happens under
        that cue instead of as dead silence after it stops. A later
        queue_info(text) finds the cache warm and plays instantly.

        Returns True if a playable PCM is ready. No-op (False) when audio_mode
        is "chime" (no speech at all) or TTS is disabled/unavailable.
        """
        if not text or not text.strip():
            return False
        try:
            from config import cfg as _cfg
            if _cfg.AUDIO_MODE == "chime" or not _cfg.TTS_ENABLED:
                return False
        except Exception:
            pass
        _t0 = time.monotonic()
        wav = self._tts_synthesize(text)
        _t1 = time.monotonic()
        if not wav:
            self.logger.info(
                f"[scene-timing] warm_tts gtts={(_t1 - _t0) * 1000:.0f}ms -> FAIL",
                module="AudioMgr")
            return False
        ok = self._ensure_pcm(wav) is not None
        self.logger.info(
            f"[scene-timing] warm_tts gtts={(_t1 - _t0) * 1000:.0f}ms "
            f"pcm={(time.monotonic() - _t1) * 1000:.0f}ms", module="AudioMgr")
        return ok

    def speak_async(self, chunks: list):
        """Warm + queue already-split sentence chunks in the background, in order.

        Used to stream the tail of a long answer: the caller speaks the first
        chunk immediately while these synthesize during its playback, so there's
        no up-front wait for the whole answer and no mid-answer gap.
        """
        chunks = [c for c in (chunks or []) if c and c.strip()]
        if not chunks:
            return

        def _bg():
            for i, ch in enumerate(chunks):
                t0 = time.monotonic()
                self.warm_tts(ch)
                dt = (time.monotonic() - t0) * 1000
                self.logger.info(
                    f"[scene-timing] tail synth chunk{i + 1} {dt:.0f}ms "
                    f"queued@{time.monotonic():.3f}",
                    module="AudioMgr",
                )
                self.queue_info(ch)

        threading.Thread(target=_bg, daemon=True, name="TTSStream").start()

    def queue_pcm_bytes(self, pcm_bytes: bytes, text: str,
                        priority: int = LOW, label: str = ""):
        """Queue ready-to-play PCM (e.g. word-cache concat). No synthesis."""
        if not pcm_bytes:
            return
        task = _Task(text, None, priority, label, pcm_bytes=pcm_bytes)
        self._pq.put((priority, task.seq, task))
        if priority < self._current_priority:
            self._interrupt.set()

    def speak_scene(self, text: str, scene_id: Optional[int] = None):
        """Speak a scene description, fastest path first.

        If every word is already cached, concatenate the cached word-audio and
        play it with ZERO network (instant). Otherwise speak the whole sentence
        via gTTS — never a partial/ompong sentence — and warm the missing words
        in the background so next time is a full hit.

        `scene_id` (from SceneMetrics.start_describe) attributes the render
        choice + timing to this describe for the /buttons latency dashboard.
        """
        text = (text or "").strip()
        if not text:
            return
        try:
            from config import cfg as _cfg
            if _cfg.AUDIO_MODE == "chime" or not _cfg.TTS_ENABLED:
                return  # no speech in chime mode
            enabled = bool(_cfg.get("word_cache_enabled", True))
        except Exception:
            enabled = True

        toks = tokenize(text)

        # "Satu blok audio" mode: cache off → always one whole-sentence synth.
        if not enabled:
            if scene_id is not None:
                scene_metrics.note_plan(scene_id, "synth", len(toks), 0)
            self._queue_scene_synth(text, scene_id)
            return

        plan = plan_utterance(text, self._word_cache.lookup)
        missing_set = set(plan.missing)
        cached_words = sum(1 for w in toks if w not in missing_set)

        if plan.mode == "concat":
            # Read every word's audio first; if any can't be read, fall through
            # to whole-sentence synthesis (never play an ompong clip).
            blobs = [_read_file_bytes(p) for p in plan.word_paths]
            if all(blobs):
                _a0 = time.monotonic()
                pcm = assemble_words(
                    blobs,
                    gap_samples=self._word_gap_samples(),
                    trim_threshold=self._word_trim_threshold(),
                    trim_margin_samples=self._word_trim_margin_samples(),
                )
                if pcm:
                    assemble_ms = (time.monotonic() - _a0) * 1000
                    self.logger.info(
                        f"[scene-timing] WORD-CACHE HIT — {len(blobs)} words, "
                        f"no network", module="AudioMgr")
                    if scene_id is not None:
                        scene_metrics.note_plan(
                            scene_id, "cache", len(toks), cached_words)
                        scene_metrics.note_cache_audio(
                            scene_id, len(pcm) / _PCM_BYTES_S * 1000, assemble_ms)
                    self.queue_pcm_bytes(pcm, text)
                    return

        # Miss (or concat failed): speak the whole sentence now, warm the gaps.
        if scene_id is not None:
            scene_metrics.note_plan(scene_id, "synth", len(toks), cached_words)
        self._queue_scene_synth(text, scene_id)
        self._warm_words_async(plan.missing or toks)

    def _queue_scene_synth(self, text: str, scene_id: Optional[int]):
        """Queue a whole-sentence scene synth (LOW), tagged so the play loop
        records its gTTS + audio timing into scene_metrics. Equivalent to
        queue_info but carries the scene_id and skips the useless WAV probe
        (a full sentence never matches a pre-recorded clip)."""
        task = _Task(text, None, LOW, "", scene_id=scene_id)
        self._pq.put((LOW, task.seq, task))
        if LOW < self._current_priority:
            self._interrupt.set()

    def cached_words_count(self) -> int:
        """Number of warmed words in the per-word cache (dashboard telemetry)."""
        try:
            return self._word_cache.count()
        except Exception:
            return 0

    # Smoothing knobs for concatenated word audio — all live-tunable via /config.
    def _word_gap_samples(self) -> int:
        """Samples between words; negative = overlap (tighter, less choppy)."""
        try:
            from config import cfg as _cfg
            gap_ms = int(_cfg.get("word_cache_gap_ms", -10))
        except Exception:
            gap_ms = -10
        return int(_PCM_RATE * gap_ms / 1000)

    def _word_trim_threshold(self) -> int:
        try:
            from config import cfg as _cfg
            if not _cfg.get("word_cache_trim_enabled", True):
                return 0
            return int(_cfg.get("word_cache_trim_threshold", 600))
        except Exception:
            return 600

    def _word_trim_margin_samples(self) -> int:
        try:
            from config import cfg as _cfg
            margin_ms = int(_cfg.get("word_cache_trim_margin_ms", 8))
        except Exception:
            margin_ms = 8
        return int(_PCM_RATE * margin_ms / 1000)

    def _warm_words_async(self, words: list):
        """Background: synthesize a few missing words in isolation via gTTS and
        store them in the word cache. Bounded per call and rate-limited so it
        never competes with foreground requests for the network/core."""
        words = [w for w in (words or []) if w and w.strip()]
        if not words:
            return
        try:
            from config import cfg as _cfg
            if _cfg.AUDIO_MODE == "chime" or not _cfg.TTS_ENABLED:
                return
            cap = int(_cfg.get("word_warm_per_call", 6))
            gap_s = float(_cfg.get("word_warm_gap_s", 0.4))
        except Exception:
            cap, gap_s = 6, 0.4

        todo = []
        for w in words:
            if self._word_cache.lookup(w) is None and w not in todo:
                todo.append(w)
            if len(todo) >= cap:
                break
        if not todo:
            return

        def _bg():
            for w in todo:
                if self._word_cache.lookup(w) is not None:
                    continue
                wav = self._tts_synthesize(w)
                if not wav:
                    continue
                pcm = self._ensure_pcm(wav)
                if not pcm:
                    continue
                try:
                    with open(pcm, "rb") as f:
                        data = f.read()
                except OSError:
                    continue
                if self._word_cache.store(w, data):
                    self.logger.debug(f"[word-cache] warmed '{w}'", module="AudioMgr")
                time.sleep(gap_s)

        threading.Thread(target=_bg, daemon=True, name="WordWarm").start()

    def clear(self):
        """Discard all pending tasks and stop current playback."""
        while not self._pq.empty():
            try:
                self._pq.get_nowait()
            except queue.Empty:
                break
        self._interrupt.set()

    def stop(self):
        """Shut down the manager thread."""
        self._stop.set()
        self._interrupt.set()

    # ─── Internals ────────────────────────────────────────────────────────────

    def _find_wav(self, text: str) -> Optional[str]:
        """Locate pre-generated WAV for this text, or return None."""
        safe = text.lower().strip()
        safe = safe.replace(" ", "_").replace("-", "_").replace(",", "")
        safe = "".join(c for c in safe if c.isalnum() or c == "_")
        for candidate in (
            os.path.join(self._audio_dir, f"{safe}.wav"),
            os.path.join(self._audio_dir, f"obj_{safe}.wav"),
            os.path.join(self._audio_dir, f"system_{safe}.wav"),
        ):
            if os.path.exists(candidate):
                return candidate
        return None

    def _ensure_pcm(self, wav_path: str) -> Optional[str]:
        """Convert WAV → PCM s16le 48 kHz mono; result cached next to source."""
        import subprocess
        pcm = os.path.splitext(wav_path)[0] + ".pcm"
        if os.path.exists(pcm):
            return pcm
        # W-1: list-args + shell=False — no command injection surface.
        try:
            ret = subprocess.run(
                [
                    "ffmpeg", "-v", "warning", "-y",
                    "-i", wav_path,
                    "-f", "s16le", "-acodec", "pcm_s16le",
                    "-ar", str(_PCM_RATE), "-ac", "1", pcm,
                ],
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            ).returncode
        except (OSError, subprocess.SubprocessError) as e:
            self.logger.exception(
                f"ffmpeg invoke failed for {wav_path}: {e}",
                module="AudioMgr", exc=e,
            )
            return None
        return pcm if ret == 0 and os.path.exists(pcm) else None

    @property
    def current_text(self) -> str:
        with self._text_lock:
            return self._current_text

    @property
    def last_caption(self) -> dict:
        """
        Most recent non-empty caption, persists after playback ends.

        Returns dict: {text, time_iso, priority}. Priority is the human-
        readable string ("critical" | "high" | "normal" | "low").
        """
        with self._text_lock:
            return dict(self._last_caption)

    # ─── Audio-mode gating (handoff §4.3) ─────────────────────────────────────

    @staticmethod
    def _priority_label(p: int) -> str:
        return {CRITICAL: "critical", HIGH: "high",
                NORMAL: "normal", LOW: "low"}.get(p, "low")

    def _tts_synthesize(self, text: str) -> Optional[str]:
        """Synthesize text via gTTS and cache to tts_cache_dir. Returns wav path or None."""
        try:
            from config import cfg as _cfg
            if not _cfg.get("tts_enabled", True):
                return None
            cache_dir = _cfg.get("tts_cache_dir", "/root/audio/tts_cache")
        except Exception:
            cache_dir = "/root/audio/tts_cache"
        try:
            from utils.tts import get_or_synthesize
            return get_or_synthesize(text, cache_dir=cache_dir)
        except Exception as e:
            self.logger.exception(
                f"TTS synthesis failed: {e}", module="AudioMgr", exc=e
            )
            return None

    def _play_task(self, task: _Task):
        """Execute playback for one task; blocks until done or interrupted."""
        # Resolve audio_mode preference fresh each task — user can change it
        # mid-session via /config without restarting the device.
        try:
            from config import cfg as _cfg
            audio_mode = _cfg.AUDIO_MODE
        except Exception:
            audio_mode = "both"

        # Gate playback against the user's preferred audio_mode.
        #   "chime"  → only pre-recorded WAV plays; tasks that would fall back
        #              to TTS are silently dropped (still cooldown-marked).
        #   "speech" → always synthesize TTS; ignore any pre-recorded WAV
        #              that _find_wav located.
        #   "both"   → legacy behaviour, no gating.
        # Cues (chime ticks, success/error tones) bypass audio_mode gating —
        # they're non-speech feedback and must play in every mode.
        if not task.is_cue:
            if audio_mode == "chime" and task.wav_path is None:
                self.logger.debug(
                    f"[Audio skipped — chime-only] {task.text}", module="AudioMgr"
                )
                return
            if audio_mode == "speech":
                task.wav_path = None  # force TTS path

        if task.label:
            with self._cd_lock:
                self._cooldown_map[task.label] = time.monotonic()

        self._current_priority = task.priority
        with self._text_lock:
            self._current_text = task.text
            # Capture last caption now (rather than after playback) so the
            # dashboard reflects what's playing in real time. Use local time
            # ISO format consistent with logger entries (no timezone suffix).
            self._last_caption = {
                "text":     task.text,
                "time_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "priority": self._priority_label(task.priority),
            }
        self._interrupt.clear()

        # Resolve the PCM to play. Prebuilt bytes (word-cache concat) skip
        # synthesis entirely; otherwise synthesize/convert the usual way.
        pcm_data = None
        src = "synth"
        _synth_s = 0.0
        if task.pcm_bytes is not None:
            pcm_data = task.pcm_bytes
            src = "word-cache"
        else:
            _synth0 = time.monotonic()
            if task.wav_path is None:
                task.wav_path = self._tts_synthesize(task.text)
            if task.wav_path:
                pcm = self._ensure_pcm(task.wav_path)
                if pcm:
                    try:
                        with open(pcm, "rb") as f:
                            pcm_data = f.read()
                    except OSError:
                        pcm_data = None
            _synth_s = time.monotonic() - _synth0
            # Attribute whole-sentence synth timing to its describe (dashboard).
            if task.scene_id is not None and pcm_data is not None:
                scene_metrics.note_synth(
                    task.scene_id, _synth_s * 1000,
                    len(pcm_data) / _PCM_BYTES_S * 1000)

        played = False
        if pcm_data:
            is_scene = (not task.is_cue and task.priority == LOW)
            if is_scene:
                self.logger.info(
                    f"[scene-timing] play START @{time.monotonic():.3f} "
                    f"({src}) text='{task.text[:30]}'", module="AudioMgr",
                )
            _t0 = time.monotonic()
            played = self._play_pcm_bytes(pcm_data)
            if is_scene:
                self.logger.info(
                    f"[scene-timing] play END   @{time.monotonic():.3f} "
                    f"dur={(time.monotonic() - _t0) * 1000:.0f}ms", module="AudioMgr",
                )

        if not played:
            self.logger.info(f"[Audio fallback] {task.text}", module="AudioMgr")

        self._current_priority = LOW
        with self._text_lock:
            self._current_text = ""

    def _play_pcm(self, pcm_path: str) -> bool:
        """Read a PCM file and play it. Thin wrapper over _play_pcm_bytes."""
        try:
            with open(pcm_path, "rb") as f:
                return self._play_pcm_bytes(f.read())
        except OSError as e:
            self.logger.exception(f"Play read error: {e}", module="AudioMgr", exc=e)
            return False

    def _play_pcm_bytes(self, pcm_data: bytes) -> bool:
        """
        Play raw PCM bytes via maix.audio.Player with interrupt support.

        player.stop() is optional — some MaixPy builds lack it.
        When stop() raises AttributeError we fall back to the deadline
        timer: the current audio chunk finishes but we return immediately
        so the higher-priority task starts as soon as possible.
        """
        if not pcm_data:
            return False
        try:
            from maix import audio as maix_audio
        except ImportError:
            return False

        try:
            player = maix_audio.Player()
            try:
                from config import cfg as _cfg
                player.volume(_cfg.AUDIO_VOLUME)
            except Exception:
                player.volume(80)
            _pc0 = time.monotonic()
            player.play(bytes(pcm_data))   # may block until done on some builds
            _play_call_s = time.monotonic() - _pc0

            # If play() blocked until the clip finished, we only hold a short
            # tail pad — NOT another full clip-duration of dead silence.
            residual_s = residual_playback_wait_s(len(pcm_data), _play_call_s)
            audio_s = len(pcm_data) / _PCM_BYTES_S
            if audio_s > 2.0:
                self.logger.info(
                    f"[scene-timing] play() blocked={_play_call_s * 1000:.0f}ms "
                    f"audio={audio_s * 1000:.0f}ms residual={residual_s * 1000:.0f}ms",
                    module="AudioMgr")
            deadline = time.monotonic() + residual_s

            while time.monotonic() < deadline:
                if self._interrupt.is_set() or self._stop.is_set():
                    try:
                        player.stop()
                    except AttributeError:
                        # player.stop() not available — can't hard-stop;
                        # return True immediately so the higher-priority task
                        # starts without waiting for the full deadline.
                        pass
                    except Exception:
                        pass
                    return True
                time.sleep(0.02)

            return True

        except Exception as e:
            self.logger.exception(f"Play error: {e}", module="AudioMgr", exc=e)
            return False

    def _loop(self):
        while not self._stop.is_set():
            try:
                _, _, task = self._pq.get(timeout=0.1)
                self._play_task(task)
            except queue.Empty:
                pass
            except Exception as e:
                self.logger.exception(f"Loop error: {e}", module="AudioMgr", exc=e)

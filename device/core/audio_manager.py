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
import time
import queue
import threading
from collections import defaultdict
from typing import Optional

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

# Monotonically increasing counter for stable ordering within same priority
_SEQ      = 0
_SEQ_LOCK = threading.Lock()


def _next_seq() -> int:
    global _SEQ
    with _SEQ_LOCK:
        _SEQ += 1
        return _SEQ


class _Task:
    __slots__ = ("text", "wav_path", "priority", "label", "seq", "is_cue")

    def __init__(self, text: str, wav_path: Optional[str],
                 priority: int, label: str, is_cue: bool = False):
        self.text     = text
        self.wav_path = wav_path
        self.priority = priority
        self.label    = label
        self.is_cue   = is_cue
        self.seq      = _next_seq()

    def __lt__(self, other: "_Task") -> bool:
        if self.priority != other.priority:
            return self.priority < other.priority
        return self.seq < other.seq


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
    so the device can announce "AuralAI menyala" the instant it powers on, with no
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

        self._pq: queue.PriorityQueue = queue.PriorityQueue()

        # label → monotonic timestamp of last play
        self._cooldown_map: dict = defaultdict(float)
        self._cd_lock = threading.Lock()

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
        """
        priority = CRITICAL if is_danger else HIGH
        poskey   = _POS_KEY.get(position, position)
        obj_id   = _LABEL_ID.get(label, label)
        phrase   = _POS_PHRASE.get(poskey, position)
        spoken   = f"{obj_id} {phrase}".strip()
        self.queue(
            text=spoken,
            priority=priority,
            label=f"obj_{label}_{poskey}",
            wav_name=f"obj_{label}_{poskey}.wav",
        )

    def queue_system(self, event: str):
        """System events (mode switches, low battery, …)."""
        self.queue(event, priority=NORMAL, label=f"sys_{event}")

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

        if task.wav_path is None:
            task.wav_path = self._tts_synthesize(task.text)

        played = False
        if task.wav_path:
            pcm = self._ensure_pcm(task.wav_path)
            if pcm:
                played = self._play_pcm(pcm)

        if not played:
            self.logger.info(f"[Audio fallback] {task.text}", module="AudioMgr")

        self._current_priority = LOW
        with self._text_lock:
            self._current_text = ""

    def _play_pcm(self, pcm_path: str) -> bool:
        """
        Play PCM via maix.audio.Player with interrupt support.

        player.stop() is optional — some MaixPy builds lack it.
        When stop() raises AttributeError we fall back to the deadline
        timer: the current audio chunk finishes but we return immediately
        so the higher-priority task starts as soon as possible.
        """
        try:
            from maix import audio as maix_audio
        except ImportError:
            return False

        try:
            with open(pcm_path, "rb") as f:
                pcm_data = f.read()

            player = maix_audio.Player()
            try:
                from config import cfg as _cfg
                player.volume(_cfg.AUDIO_VOLUME)
            except Exception:
                player.volume(80)
            player.play(bytes(pcm_data))   # non-blocking start

            duration_s = len(pcm_data) / _PCM_BYTES_S + 0.15
            deadline   = time.monotonic() + duration_s

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

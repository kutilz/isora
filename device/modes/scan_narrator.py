"""
Online navigation — cloud narration layered over explorer's YOLO.

ACTION in explorer switches it on and off ("navigasi daring aktif / mati").
While it is on, every explorer tick calls step(): YOLO keeps running and keeps
announcing hazards, and every scan_interval_s a photo goes to the cloud with
SCENE_PROMPT_SCAN, whose one-sentence answer is spoken at LOW priority.

Why the cloud call runs on a worker thread
──────────────────────────────────────────
The describe button makes its call on the AI loop thread, which stops YOLO for
the whole round-trip (~3 s measured). For one press that is a pause; for a
narrator running every few seconds it would be YOLO switched off. So only the
JPEG encode happens on the AI thread — the one thread allowed near the camera.
The HTTP call AND the speaking run on a worker: speak_scene's word-cache concat
alone held the AI loop for 716 ms on isora-88dd. The worker hands speak_scene a
still_wanted() check, so a switch-off during that render is still honoured.

Timing rules
────────────
  * One call in flight at most. A slow network makes updates rarer; it never
    stacks requests on a 128 MB board.
  * The next photo is taken no sooner than scan_interval_s after the previous
    one, and only once the audio is quiet, so the narrator never talks over
    itself or over a YOLO alert.
  * An answer that lands more than scan_stale_s after its photo is dropped: at
    walking pace the user is metres past the place it describes.
  * A failure is spoken once per outage, then retried every scan_retry_s.
  * While a narration plays, explorer speaks hazards only (holds_floor()).
    Otherwise every "orang di depan" would cut the sentence off mid-word.
"""

import threading
import time

from config import cfg
from utils import diag
from utils.scene_prompt import scrub_animals


def _spawn_daemon(fn):
    threading.Thread(target=fn, daemon=True, name="ScanCall").start()


def _speech_on() -> bool:
    """Whether a narration would actually be heard. In chime-only mode
    speak_scene says nothing, so a call would be paid for and thrown away."""
    return cfg.AUDIO_MODE != "chime" and cfg.TTS_ENABLED


def ai_key_present() -> bool:
    try:
        from core.cloud import _ai_key_present
    except Exception:
        return True          # let the call itself fail and say why
    return _ai_key_present()


# SCENE_PROMPT_SCAN tells the model to answer exactly this when a photo holds
# nothing worth saying. It is a marker, not speech: read out every cycle it was
# "Belum ada yang perlu disebut." every ~8 s while walking a quiet corridor —
# awkward, and noise that buries the sentences that matter. Matched on the
# opening words, so a model that drops the full stop or adds a word after it
# is still caught.
NOTHING_TO_REPORT = "belum ada yang perlu disebut"


def is_nothing_to_report(text: str) -> bool:
    norm = " ".join((text or "").lower().replace(".", " ").split())
    return norm.startswith(NOTHING_TO_REPORT)


class ScanNarrator:

    def __init__(self, orch, clock=time.monotonic, spawn=None):
        self.orch    = orch
        self._clock  = clock
        self._spawn  = spawn or _spawn_daemon
        self._lock   = threading.Lock()
        self._active = False
        # Bumped by every start/stop, so an answer to a photo taken before the
        # user switched it off (or left explorer) is never spoken afterwards.
        self._gen      = 0
        self._inflight = False
        self._next_at  = 0.0
        self._failing  = False
        self._holding  = False

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    def start(self):
        with self._lock:
            self._active  = True
            self._gen    += 1
            self._failing = False
            self._holding = False
            # First photo as soon as the audio is quiet, i.e. right after
            # "navigasi daring aktif" has been said.
            self._next_at = 0.0

    def stop(self) -> bool:
        """Switch off. Returns whether it was on. Safe from any thread."""
        with self._lock:
            was = self._active
            self._active  = False
            self._gen    += 1
            self._holding = False
            return was

    def holds_floor(self) -> bool:
        """True while a narration is queued or playing."""
        with self._lock:
            return self._active and self._holding

    def step(self):
        """One narrator pass. AI loop thread only (it encodes the frame)."""
        now = self._clock()
        am = getattr(self.orch, "audio_manager", None)
        quiet = am is not None and am.is_quiet()
        with self._lock:
            if not self._active:
                return
            if self._inflight:
                return
            # The worker raised the flag before queueing; only once it is done
            # AND the audio has drained has the sentence really finished.
            if quiet:
                self._holding = False
            if now < self._next_at:
                return
            gen = self._gen
        if not quiet or not _speech_on():
            return
        engine = getattr(self.orch, "ai_engine", None)
        jpeg = engine._frame_jpeg() if engine is not None else b""
        if not jpeg:
            return
        prompt = cfg.PROMPT_SCAN
        with self._lock:
            if not self._active or gen != self._gen:
                return
            self._inflight = True
            self._next_at  = now + cfg.SCAN_INTERVAL_S
        self._spawn(lambda: self._call(gen, now, jpeg, prompt))

    def _current(self, gen) -> bool:
        with self._lock:
            return self._active and gen == self._gen

    def _call(self, gen, shot_at, jpeg, prompt):
        """Worker thread: the cloud round-trip, then the answer."""
        try:
            text, err = None, None
            photo = diag.save_frame(jpeg, cfg, "navigasi")
            try:
                from adapters import get_adapter
                text = get_adapter(cfg.AI_PROVIDER, cfg).describe_scene(jpeg, prompt)
                diag.frame_result(photo, text)
            except Exception as e:
                err = e
                diag.frame_result(photo, e, ok=False)
            self._deliver(gen, shot_at, text, err)
        except Exception as e:
            log = getattr(self.orch, "logger", None)
            if log:
                log.warn(f"[scan] delivery failed: {e}", module="ScanNarrator")
        finally:
            with self._lock:
                self._inflight = False

    def _deliver(self, gen, shot_at, text, err):
        if not self._current(gen):
            return
        now = self._clock()
        age = now - shot_at
        am = getattr(self.orch, "audio_manager", None)
        log = getattr(self.orch, "logger", None)
        if err is not None:
            with self._lock:
                first = not self._failing
                self._failing = True
                self._next_at = max(self._next_at, now + cfg.SCAN_RETRY_S)
            if log:
                log.warn(f"[scan] call failed after {age:.1f}s: {err}",
                         module="ScanNarrator")
            if first and am is not None:
                from core.ai_engine import _net_failure_cue
                am.queue_system(_net_failure_cue(err, "gagal_menganalisis"))
            return
        with self._lock:
            self._failing = False
        text = scrub_animals((text or "").strip())
        if not text:
            return
        if age > cfg.SCAN_STALE_S:
            if log:
                log.info(f"[scan] dropped, {age:.1f}s stale: {text}",
                         module="ScanNarrator")
            return
        if log:
            log.info(f"[scan] {age:.1f}s: {text}", module="ScanNarrator")
        if is_nothing_to_report(text):
            return          # stay silent; the next photo follows on schedule
        if am is None:
            return
        with self._lock:
            if not self._active or gen != self._gen:
                return
            self._holding = True
        am.speak_scene(text, still_wanted=lambda: self._current(gen))

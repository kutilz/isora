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
from contextlib import contextmanager
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

# How long a queued navigation alert stays worth speaking. Past this the
# position it describes is old enough to mislead a walking user.
_NAV_ALERT_TTL_S = 3.0

# Most background scene renders allowed in flight at once. Two covers the real
# case (a describe finishing while the next one starts); beyond that they are
# races nobody is listening to any more. See speak_scene.
_MAX_SCENE_SYNTH = 2

# How long one press acknowledgement is protected from the next press's flush.
# Roughly the length of chime_press.wav: long enough that a mashed sequence
# still makes a sound, short enough that a deliberate second press is not
# swallowed. See user_barge_in.
_PRESS_CUE_HOLD_S = 0.25

# MaixPy's Player.play() accepts at most 512 KiB in ONE call. Hand it more and
# the driver keeps the first 512 KiB, DROPS the rest and returns ERR_RUNTIME:
#   [E] play data length is incorrect, write 1071360 bytes, returns 524288 bytes
# At 48 kHz s16le mono that ceiling is 5.46 s, so short cues (chimes, greetings,
# mode names) always fit and nothing looked broken — but every scene description
# longer than ~5.4 s was cut clean in half, mid-sentence. Feed the player in
# sub-limit chunks instead, PACED to the playback rate: writing chunks
# back-to-back just overflows the same ring buffer (the driver then takes 512
# bytes at a time), so each write must wait for the buffer to drain. 2 s stays
# far under the cap while still refilling well ahead of the play head.
_PLAY_CHUNK_S     = 2.0
_PLAY_CHUNK_BYTES = int(_PCM_BYTES_S * _PLAY_CHUNK_S)   # 192000 B
_PLAY_DRIVER_LIMIT_BYTES = 524288

# ── Volume, in software ──────────────────────────────────────────────────────
# MaixPy 4.5.1 does not implement Player.volume(); it raises
#   RuntimeError: Not implemented: Not support now
# on every call. Confirmed on the shipping hardware. Both call sites used to
# swallow that with a bare `except: pass` and play at the codec default, so
# audio_volume was a number four different UIs displayed, the volume chord
# gesture adjusted, and the config persisted — that never reached the speaker.
# A blind user pressing volume-down heard nothing change, pressed again, and
# ended up pinned at the floor with the device exactly as loud as before.
#
# So scale the samples ourselves. audioop.mul is a C routine: measured on this
# board at 6.9 ms per second of audio, against 1068 ms for the same loop in
# pure Python — which is why there is no pure-Python fallback. If audioop is
# gone (it is slated for removal in 3.13) we play at full level rather than
# spend a second of CPU per second of speech.
#
# Linear on amplitude, matching the "percent" the UI shows: 20 % lands near
# -14 dB, quiet but still clearly audible, which is what a floor should be.


def set_player_volume(player, volume, pcm_data: bytes) -> bytes:
    """Apply `volume` to `player` if the firmware can, otherwise to the samples.

    Returns the PCM to actually play. Deliberately stateless — an earlier
    version cached "this firmware has no volume support" in a module global,
    which made the behaviour depend on what had run before it. One failed call
    per clip is nothing next to a 48 kHz playback.
    """
    try:
        player.volume(volume)
        return pcm_data
    except Exception:
        return apply_software_gain(pcm_data, volume)


def apply_software_gain(pcm_data: bytes, volume: int) -> bytes:
    """Scale s16le mono PCM to `volume` percent. Returns the input unchanged
    when no scaling is needed or possible."""
    try:
        vol = int(volume)
    except (TypeError, ValueError):
        return pcm_data
    if vol >= 100 or not pcm_data:
        return pcm_data
    vol = max(0, min(100, vol))
    try:
        import audioop
    except Exception:
        return pcm_data
    try:
        return audioop.mul(pcm_data, 2, vol / 100.0)
    except Exception:
        return pcm_data


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


# ── Codec gate ────────────────────────────────────────────────────────────────
# The MaixCAM codec accepts exactly ONE open maix.audio.Player. Two paths open
# one: play_wav_blocking (boot cues, before an AudioManager exists) and
# AudioManager._play_pcm_bytes (the queue worker). At boot they overlap — the
# "menghubungkan ke wifi" cue is still sounding when the ready chime is queued —
# and whoever lost the race got `RuntimeError: failed to open PCM`, which the
# caller swallowed into a text-only fallback. The device then never said it was
# ready. Serialising the two here makes the loser wait its turn instead.
_DEVICE_LOCK   = threading.Lock()
_DEVICE_WAIT_S = 8.0        # cap: a wedged holder must not mute the queue forever


@contextmanager
def _codec():
    """Hold the codec for one clip. Yields True if the slot was actually ours.

    On timeout we yield False and let the caller try anyway: the holder may
    have died without releasing, and attempting is strictly better than the
    guaranteed silence of giving up.
    """
    got = _DEVICE_LOCK.acquire(timeout=_DEVICE_WAIT_S)
    try:
        yield got
    finally:
        if got:
            _DEVICE_LOCK.release()


def _next_seq() -> int:
    global _SEQ
    with _SEQ_LOCK:
        _SEQ += 1
        return _SEQ


# Sentence boundary: a .!?; followed by whitespace. Lets us speak a long answer
# one sentence at a time so the first words come out while the rest is still
# being synthesized (see AudioManager._queue_scene_synth). The semicolon counts
# because the vision models routinely join two independent clauses with one
# ("Tidak tampak orang; area di depan tertutup kabut"), and without it that
# whole description is a single un-splittable chunk.
_SENT_SPLIT = re.compile(r"(?<=[.!?;])\s+")

# Upper bound on how long background word-warming defers to the playback queue.
# Warming is never urgent, but it must not be starved forever by back-to-back
# describes either.
_WARM_DEFER_MAX_S = 30.0

# Boot-time pre-warm of the speech backend (see warm_speech_stack). The phrase
# is short and generic on purpose: it only has to make gTTS do its lazy imports
# and open its first session, and it costs one small cache entry.
_WARM_PHRASE            = "siap"
_WARM_STACK_RETRIES     = 4
_WARM_STACK_RETRY_GAP_S = 5.0


# A chunk longer than this is worth breaking at a comma even though it is one
# sentence: synthesis time rises with length, and the description the vision
# model returns is very often a single 100+ char sentence with exactly one
# comma in the middle of it, which would otherwise be one long un-split call.
_COMMA_SPLIT_MIN_CHARS = 70
# …but never leave a fragment too short to be worth its own round-trip.
_COMMA_MIN_PART_CHARS  = 25


# Words that open a new clause in Indonesian, so a breath before them is what a
# person reading aloud would do anyway. Used only when a long sentence has no
# comma to break at — a break anywhere else mid-clause is audible, because each
# chunk is rendered with its own intonation contour and the two don't join.
# Deliberately excludes "yang", "di", "ke", "untuk": those bind tightly to what
# precedes them and pausing before one sounds like a stutter.
_CLAUSE_OPENERS = (
    "tanpa", "dan", "serta", "sementara", "sedangkan", "namun", "tetapi",
    "atau", "dengan", "sambil", "lalu", "kemudian",
)


def _split_at_clause(chunk: str) -> list:
    """Break one over-long sentence in half at its most natural pause, or not at all.

    Preference order is the order a reader would pick: a comma first, then a
    clause-opening word. Whichever candidate sits closest to the middle wins, so
    the first chunk — the one the user is waiting on — is as short as it can be
    without stranding a fragment.
    """
    if len(chunk) < _COMMA_SPLIT_MIN_CHARS:
        return [chunk]

    mid = len(chunk) // 2

    def _best(cuts):
        """cuts: (head_end, tail_start) offsets. Nearest the middle, or None."""
        ok = [c for c in cuts
              if len(chunk[:c[0]].strip()) >= _COMMA_MIN_PART_CHARS
              and len(chunk[c[1]:].strip()) >= _COMMA_MIN_PART_CHARS]
        return min(ok, key=lambda c: abs(c[0] - mid)) if ok else None

    cut = _best([(i + 1, i + 1) for i, ch in enumerate(chunk) if ch == ","])
    if cut is None:
        cut = _best([(m.start(), m.start()) for m in re.finditer(
            r"\s(?=(?:%s)\s)" % "|".join(_CLAUSE_OPENERS), chunk)])
    if cut is None:
        return [chunk]
    return [chunk[:cut[0]].strip(), chunk[cut[1]:].strip()]


def split_sentences(text: str, max_chunks: int = 3) -> list:
    """Split `text` into at most `max_chunks` speakable chunks.

    Sentence boundaries first; a single over-long sentence then falls back to
    its middle comma, because "one sentence" is the common case for a scene
    description and leaving it whole is what makes the user wait. Near-empty
    input returns []. Over-splitting is avoided by merging the tail once
    max_chunks is reached, so we never spawn a long string of tiny gTTS calls
    on a one-core device.
    """
    text = (text or "").strip()
    if not text:
        return []
    parts = [p.strip() for p in _SENT_SPLIT.split(text) if p.strip()]
    if len(parts) == 1 and max_chunks > 1:
        parts = _split_at_clause(parts[0])
    if len(parts) > max_chunks:
        head = parts[: max_chunks - 1]
        head.append(" ".join(parts[max_chunks - 1:]))
        parts = head
    return parts


class _Task:
    __slots__ = ("text", "wav_path", "priority", "label", "seq", "is_cue",
                 "pcm_bytes", "pcm_path", "created")

    def __init__(self, text: str, wav_path: Optional[str],
                 priority: int, label: str, is_cue: bool = False,
                 pcm_bytes: Optional[bytes] = None,
                 pcm_path: Optional[str] = None):
        self.text      = text
        self.wav_path  = wav_path
        self.priority  = priority
        self.label     = label
        self.is_cue    = is_cue
        # Ready-to-play PCM (e.g. concatenated word-cache audio); when set,
        # playback skips WAV lookup / synthesis entirely.
        self.pcm_bytes = pcm_bytes
        # Already-rendered 48 kHz PCM on disk (scene chunks). Read at play time
        # rather than held in memory: this board runs with ~4 MB free and one
        # description is ~800 KB of PCM.
        self.pcm_path  = pcm_path
        self.seq       = _next_seq()
        # When this task was queued. Navigation alerts describe where something
        # was AT THAT MOMENT; spoken late they send a walking user the wrong
        # way. See the staleness check in _play_task.
        self.created   = time.monotonic()

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


# Freshness is an mtime EQUALITY, so the tolerance only has to absorb the
# coarsest timestamp granularity a .pcm can land on (vfat rounds to 2 s).
_PCM_MTIME_SLACK_S = 2.0


def _pcm_is_fresh(wav_path: str, pcm_path: str) -> bool:
    """True when `pcm_path` was derived from the CURRENT `wav_path`.

    The .pcm next to each WAV is a build artefact, and the original check was a
    bare `os.path.exists`. That meant a replaced WAV — new chime set, a
    re-recorded cue, a brand swap — kept playing the PREVIOUS sound forever,
    with nothing in the logs to say why: the file on disk was right and the
    device was reading a stale sibling.

    The test is "the .pcm carries its source's mtime" (stamped by _stamp_pcm),
    NOT "the .pcm is newer than its source". The device boots with the wall
    clock at the epoch and NTP jumps it forward at an unpredictable point during
    boot, while every WAV arrives over SSH carrying a present-day mtime. So a
    .pcm rebuilt pre-NTP is stamped 1970 against a 2026 WAV: under a `pcm >= wav`
    test it is stale forever, the cache never hits once, and every queue_cue —
    including the CRITICAL "orang di depan" obstacle alert — pays a fresh ffmpeg
    spawn before it is audible. Equality against the source cannot be broken by
    a clock jump in either direction.

    A missing/unreadable pcm falls through to "rebuild it" — the
    expensive-but-correct direction.
    """
    try:
        delta = os.path.getmtime(pcm_path) - os.path.getmtime(wav_path)
    except OSError:
        return False
    return abs(delta) <= _PCM_MTIME_SLACK_S


def _stamp_pcm(wav_path: str, pcm_path: str) -> None:
    """Copy the source WAV's mtime onto the .pcm just built from it.

    This is what makes _pcm_is_fresh independent of the device clock.
    Best-effort: if the stamp fails the only cost is rebuilding next time.
    """
    try:
        st = os.stat(wav_path)
        os.utime(pcm_path, (st.st_atime, st.st_mtime))
    except OSError:
        pass


def _ensure_pcm_standalone(wav_path: str) -> Optional[str]:
    """Convert WAV → PCM s16le 48 kHz mono, cached next to source. Module-level
    twin of AudioManager._ensure_pcm for use before an AudioManager exists."""
    import subprocess
    pcm = os.path.splitext(wav_path)[0] + ".pcm"
    if _pcm_is_fresh(wav_path, pcm):
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
    if ret != 0 or not os.path.exists(pcm):
        return None
    _stamp_pcm(wav_path, pcm)
    return pcm


def play_wav_blocking(wav_name: str, audio_dir: str = "/root/audio",
                      volume: int = 80) -> bool:
    """
    Play a single pre-recorded WAV synchronously via maix.audio.Player.

    Safe to call at the very start of boot — before AudioManager/AIEngine exist —
    so the device can announce "I-Sora menyala" the instant it powers on, with no
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
    with _codec():
        try:
            with open(pcm, "rb") as f:
                pcm_data = f.read()
            player = maix_audio.Player()
            # Same story as AudioManager._play_pcm_bytes: this firmware has no
            # hardware volume, so scale the samples rather than play every boot
            # cue at the codec default.
            pcm_data = set_player_volume(player, volume, pcm_data)
            # Same 512 KiB per-call driver cap as AudioManager._play_pcm_bytes:
            # chunk + pace, or anything past 5.46 s is dropped. Boot greetings are
            # short today, but this path takes an arbitrary WAV name.
            t0 = time.monotonic()
            written = 0
            for off in range(0, len(pcm_data), _PLAY_CHUNK_BYTES):
                chunk = pcm_data[off:off + _PLAY_CHUNK_BYTES]
                player.play(bytes(chunk))
                written += len(chunk)
                target = written / _PCM_BYTES_S - _PLAY_CHUNK_S
                while True:
                    slack = target - (time.monotonic() - t0)
                    if slack <= 0:
                        break
                    time.sleep(min(0.02, slack))
            duration_s = len(pcm_data) / _PCM_BYTES_S + 0.15
            deadline = t0 + duration_s
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
        # When the last press acknowledgement was started. Guards against a
        # burst of presses cancelling each other's cue — see user_barge_in.
        self._last_press_cue_at = 0.0
        # In-flight background scene renders (see speak_scene).
        self._synth_lock   = threading.Lock()
        self._synth_active = 0
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

        # Generation counter for the background scene streamer. A scene is
        # queued one sentence at a time, so between chunks the user may have
        # barged in (clear() → a new press, a mode switch). Bumping this on
        # every clear lets the in-flight streamer notice it has been abandoned
        # and drop its remaining chunks, instead of speaking the tail of a
        # description the user already walked away from.
        self._scene_gen = 0
        self._scene_gen_lock = threading.Lock()

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

        A press that lands while the PREVIOUS press's chime is still sounding
        does not flush again. Every press used to clear the queue and re-queue
        its own cue, so a fast sequence cancelled each acknowledgement with the
        next one and the device went completely silent — the single worst thing
        it can do to a blind user, who then presses harder because nothing
        happened. The queue is already empty in that window and a cue is
        already playing, so there is nothing to gain by restarting it.
        """
        now = time.monotonic()
        if (now - self._last_press_cue_at) < _PRESS_CUE_HOLD_S:
            self._last_press_cue_at = now
            return
        self._last_press_cue_at = now
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

        # The per-word cache exists to dodge a slow, erratic gTTS round-trip.
        # The openai backend has neither problem, and splicing independently
        # rendered words would both cost prosody and — since warmed words are
        # whatever backend rendered them — risk switching voice mid-session.
        # So on that backend the sentence is simply spoken as one.
        if self._tts_backend() == "openai":
            enabled = False

        # "Satu blok audio" mode: cache off → always one whole-sentence synth.
        if not enabled:
            if scene_id is not None:
                scene_metrics.note_plan(scene_id, "synth", len(toks), 0)
            self._queue_scene_synth(text, scene_id)
            return

        plan = plan_utterance(text, self._word_cache.lookup,
                              max_words=self._word_cache_max_words())
        # plan.cached_count, not a set-difference against plan.missing: when
        # the max_words cap fires plan.missing lists EVERY token (for warming)
        # even on a full cache hit, which would record a warm cache as 0-cached.
        cached_words = plan.cached_count

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
        """Speak a scene description, first words as early as possible.

        Two avoidable costs used to sit between the success chime and the first
        spoken word:

          * synthesis ran inside the play loop, so the gTTS round-trip did not
            even START until the chime queued ahead of it had finished, and
          * it was one call for the whole description — and gTTS scales with
            length. Measured on this device: 155 chars costs ~5.3 s of gTTS
            plus ~1.4 s of ffmpeg decode, against ~1.8 s + ~1.1 s for an
            89-char half.

        So render from a background thread instead, one sentence at a time.
        Chunk 1 is already synthesizing while the chime still sounds, and the
        tail renders underneath chunk 1's playback (~8 s of speech buys ~1 s of
        synth), landing with no audible seam. First word moves from ~6.7 s
        after the AI answer to ~2.9 s.

        Each chunk is queued at LOW in order, carrying the path to its rendered
        PCM — a path rather than the bytes because this board runs with ~4 MB
        free and one description is ~800 KB. scene_metrics timing is recorded
        here, since the play loop no longer synthesizes anything to time.
        """
        chunks = split_sentences(text, max_chunks=self._scene_stream_chunks())
        if not chunks:
            return
        with self._scene_gen_lock:
            self._scene_gen += 1
            gen = self._scene_gen
        t0 = time.monotonic()

        # Fire every chunk's render at once rather than one after another. Each
        # is dominated by a network round-trip, so serially the tail arrived at
        # chunk1+chunk2 (~10 s) — sometimes AFTER chunk 1 had finished playing,
        # which is an audible gap mid-sentence. Concurrently it arrives at
        # max(chunk1, chunk2) instead, comfortably inside chunk 1's playback.
        # Ordering is unaffected: results are collected and queued in order.
        renders: list = [None] * len(chunks)

        def _render_one(idx: int):
            t = time.monotonic()
            renders[idx] = (self._render_pcm(chunks[idx]), time.monotonic() - t)

        workers = [threading.Thread(target=_render_one, args=(i,), daemon=True,
                                    name=f"SceneChunk{i}")
                   for i in range(len(chunks))]

        def _bg():
            for w in workers:
                w.start()
            first_ms = None
            total_audio_ms = 0.0
            for i, chunk in enumerate(chunks):
                if self._scene_abandoned(gen):
                    return
                workers[i].join()
                pcm, render_s = renders[i] or (None, 0.0)
                # Re-check AFTER the round-trip: that is where the user's press
                # most likely landed.
                if self._scene_abandoned(gen):
                    return
                audio_ms = 0.0
                if pcm:
                    try:
                        audio_ms = os.path.getsize(pcm) / _PCM_BYTES_S * 1000
                    except OSError:
                        pass
                total_audio_ms += audio_ms
                if first_ms is None:
                    first_ms = (time.monotonic() - t0) * 1000
                    self.logger.info(
                        f"[scene-timing] chunk1 ready {first_ms:.0f}ms "
                        f"(tts[{self._tts_backend()}]="
                        f"{render_s * 1000:.0f}ms, "
                        f"{len(chunk)} of {len(text)} chars, "
                        f"{len(chunks)} chunks)", module="AudioMgr")
                    if scene_id is not None:
                        scene_metrics.note_synth(scene_id, first_ms, audio_ms)
                else:
                    self.logger.info(
                        f"[scene-timing] chunk{i + 1} ready "
                        f"{(time.monotonic() - t0) * 1000:.0f}ms "
                        f"(tts={render_s * 1000:.0f}ms)", module="AudioMgr")
                # pcm=None (synthesis failed) still gets queued: the play loop
                # retries and logs the fallback, same as before.
                task = _Task(chunk, None, LOW, "", pcm_path=pcm)
                self._pq.put((LOW, task.seq, task))
            # Second pass over the same record so audio_ms covers the whole
            # description while to_audio_ms stays "when the user heard word one".
            if scene_id is not None and first_ms is not None:
                scene_metrics.note_synth(scene_id, first_ms, total_audio_ms)

        # Cap the number of synth threads in flight. Each one holds a network
        # session and a PCM buffer, and every ACTION press starts another: on a
        # 128MB swapless single-core board a mashing user could stack them
        # faster than they finish, and the abandonment check only stops a
        # thread BETWEEN chunks — it cannot stop one blocked in a socket read.
        # An extra describe nobody waited for is worth less than the memory.
        with self._synth_lock:
            if self._synth_active >= _MAX_SCENE_SYNTH:
                self.logger.warn(
                    "Scene synthesis skipped — %d already in flight"
                    % self._synth_active, module="AudioMgr")
                return
            self._synth_active += 1

        def _bg_guarded():
            try:
                _bg()
            finally:
                with self._synth_lock:
                    self._synth_active -= 1

        threading.Thread(target=_bg_guarded, daemon=True,
                         name="SceneSynth").start()

    def _scene_abandoned(self, gen: int) -> bool:
        """True once a clear() (barge-in, mode switch) has superseded this scene."""
        with self._scene_gen_lock:
            return gen != self._scene_gen

    def _scene_stream_chunks(self) -> int:
        """How many sentence chunks a scene description is streamed in.
        1 disables streaming — one whole-sentence synth, the old behaviour."""
        try:
            from config import cfg as _cfg
            return max(1, int(_cfg.get("scene_stream_chunks", 3)))
        except Exception:
            return 3

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

    def _word_cache_max_words(self) -> int:
        """Cap on sentence length for word-cache concat mode. A long free-form
        sentence (e.g. "detail" verbosity) spliced from independently
        synthesized words sounds robotic no matter how smooth each seam is —
        past this length we go straight to one fluent gTTS render instead
        (words still warm in the background). 0 disables the cap."""
        try:
            from config import cfg as _cfg
            return int(_cfg.get("word_cache_max_words", 12))
        except Exception:
            return 12

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
            # Wait out the description that triggered this. These are gTTS
            # calls on the same link and the same core as the scene chunks
            # still being synthesized behind the chime — warming a word for
            # *next* time must never delay the sentence the user is waiting on
            # right now. Bounded so back-to-back describes can't starve it.
            deadline = time.monotonic() + _WARM_DEFER_MAX_S
            while time.monotonic() < deadline:
                if self._pq.empty() and not self.current_text:
                    break
                if self._stop.is_set():
                    return
                time.sleep(0.25)

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
        with self._scene_gen_lock:
            self._scene_gen += 1   # abandon any half-spoken scene description
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
        """Convert WAV → PCM s16le 48 kHz mono; result cached next to source.

        Rebuilt whenever the cached PCM does not carry its source WAV's mtime —
        see _pcm_is_fresh for why "it exists" was not a safe enough test, and
        why the test is not "is it newer".
        """
        import subprocess
        pcm = os.path.splitext(wav_path)[0] + ".pcm"
        if _pcm_is_fresh(wav_path, pcm):
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
        if ret != 0 or not os.path.exists(pcm):
            return None
        _stamp_pcm(wav_path, pcm)
        return pcm

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

    def warm_speech_stack(self, delay_s: float = 0.0):
        """Pay the speech backend's one-off startup cost now, not on the first press.

        `import gtts` alone measures 6.0 s on this board — it drags requests,
        urllib3 and certifi off slow flash — and gTTS's own first render costs
        another 3.7 s of lazy imports and session setup. _synthesize imports
        inside the function, so all of that landed on the FIRST describe after
        every boot: ~9 s of silence after the chime, against ~0.6 s for the same
        sentence once warm. It looked exactly like a flaky network, and was not.

        Runs on a background thread, started after boot is marked ready so it
        never shows up in time-to-ready. Every failure is ignored: this is pure
        pre-warming, and the normal path still works cold if it never finishes.
        """
        def _bg():
            if delay_s:
                time.sleep(delay_s)
            backend = self._tts_backend()
            t0 = time.monotonic()
            if backend == "gtts":
                try:
                    import gtts  # noqa: F401
                except Exception as e:
                    self.logger.warn(f"[warm] gtts import failed: {e}",
                                     module="AudioMgr")
                    return
                imported_ms = (time.monotonic() - t0) * 1000
                # WiFi may still be associating; a render is what warms gTTS's
                # own lazy setup, so it is worth a few retries.
                for attempt in range(_WARM_STACK_RETRIES):
                    if self._stop.is_set():
                        return
                    if self._tts_synthesize(_WARM_PHRASE):
                        self.logger.info(
                            f"[warm] speech stack ready in "
                            f"{(time.monotonic() - t0) * 1000:.0f}ms "
                            f"(import {imported_ms:.0f}ms)", module="AudioMgr")
                        return
                    time.sleep(_WARM_STACK_RETRY_GAP_S * (attempt + 1))
                self.logger.warn("[warm] speech stack not warmed (no network yet)",
                                 module="AudioMgr")
            else:
                # The openai backend needs no import (urllib is stdlib), so only
                # DNS + the TLS handshake are worth pre-paying — and a render
                # would cost real money on every boot.
                try:
                    import socket
                    import ssl
                    ip = socket.getaddrinfo("api.openai.com", 443, socket.AF_INET,
                                            socket.SOCK_STREAM)[0][4][0]
                    sock = socket.create_connection((ip, 443), timeout=10)
                    ssl.create_default_context().wrap_socket(
                        sock, server_hostname="api.openai.com").close()
                    self.logger.info(
                        f"[warm] openai TLS warmed in "
                        f"{(time.monotonic() - t0) * 1000:.0f}ms", module="AudioMgr")
                except Exception as e:
                    self.logger.debug(f"[warm] openai warm skipped: {e}",
                                      module="AudioMgr")

        threading.Thread(target=_bg, daemon=True, name="TTSWarm").start()

    def _tts_backend(self) -> str:
        """"openai" or "gtts" — which cloud voice renders free-form speech.

        gTTS is the default despite being the slower and more erratic of the
        two: the OpenAI voices read Indonesian with an English accent, and a
        user who only has the audio notices that far more than a second of
        latency. "auto" picks openai whenever a key is configured, for anyone
        who has auditioned a gpt-4o-mini-tts voice and prefers it.
        """
        try:
            from config import cfg as _cfg
            choice = str(_cfg.get("tts_provider", "auto")).lower()
            if choice == "gtts":
                return "gtts"
            if choice == "openai" or (choice == "auto" and _cfg.OPENAI_API_KEY):
                return "openai"
        except Exception:
            pass
        return "gtts"

    def _render_pcm(self, text: str) -> Optional[str]:
        """Path to ready-to-play 48 kHz PCM for `text`, by the fastest route.

        The openai backend answers in raw PCM, so this never spawns ffmpeg —
        worth a flat 1.2-1.8 s per sentence on this SoC. Any failure (no key,
        HTTP error, no network) falls through to gTTS: a slower voice is always
        better than a silent device.
        """
        if self._tts_backend() == "openai":
            try:
                from config import cfg as _cfg
                from utils.tts import get_or_synthesize_pcm
                pcm = get_or_synthesize_pcm(
                    text,
                    api_key=_cfg.OPENAI_API_KEY,
                    cache_dir=_cfg.get("tts_cache_dir", "/root/audio/tts_cache"),
                    model=_cfg.get("tts_openai_model", "gpt-4o-mini-tts"),
                    voice=_cfg.get("tts_openai_voice", "alloy"),
                    instructions=_cfg.get("tts_openai_instructions", ""),
                    timeout_s=float(_cfg.get("tts_openai_timeout_s", 15.0)),
                )
            except Exception as e:
                self.logger.exception(
                    f"OpenAI TTS failed, falling back to gTTS: {e}",
                    module="AudioMgr", exc=e,
                )
                pcm = None
            if pcm:
                return pcm
            self.logger.warn("OpenAI TTS unavailable — using gTTS",
                             module="AudioMgr")

        wav = self._tts_synthesize(text)
        return self._ensure_pcm(wav) if wav else None

    def _tts_synthesize(self, text: str) -> Optional[str]:
        """Synthesize text via gTTS and cache to tts_cache_dir. Returns wav path or None."""
        try:
            from config import cfg as _cfg
            if not _cfg.get("tts_enabled", True):
                return None
            cache_dir = _cfg.get("tts_cache_dir", "/root/audio/tts_cache")
            # gTTS on a phone hotspot has been seen taking 13 s for a sentence
            # it normally renders in 2. The old 8 s ceiling threw those away and
            # then paid for a retry, which is strictly slower than waiting.
            timeout_s = float(_cfg.get("tts_gtts_timeout_s", 20.0))
        except Exception:
            cache_dir = "/root/audio/tts_cache"
            timeout_s = 20.0
        try:
            from utils.tts import get_or_synthesize
            return get_or_synthesize(text, cache_dir=cache_dir,
                                     timeout_s=timeout_s)
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

        # Drop a navigation alert that has gone stale in the queue. "motor di
        # agak kiri, dekat" is a statement about a moment; spoken four seconds
        # later to someone still walking it is not merely useless, it points
        # them at where the hazard WAS. Nothing else expires — a mode name or a
        # description is still true whenever it is finally heard.
        if (task.label or "").startswith("nav_"):
            age = time.monotonic() - task.created
            if age > _NAV_ALERT_TTL_S:
                self.logger.debug(
                    "[nav dropped — %.1fs stale] %s" % (age, task.text),
                    module="AudioMgr")
                return

        # Stamp the cooldown BEFORE playing so a duplicate queued in the same
        # instant is still gated — but remember the previous stamp, because a
        # task that gets barged out a few milliseconds in was never actually
        # heard, and leaving the stamp behind suppresses the NEXT attempt too.
        # That is what made mashing MODE silent: each mode name was cut off by
        # the following press cue, yet still blocked its successor for the full
        # 2s cooldown, so the user cycled four modes and heard none of them.
        prev_cd = None
        if task.label:
            with self._cd_lock:
                prev_cd = self._cooldown_map.get(task.label)
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

        # Resolve the PCM to play. A scene chunk arrives pre-rendered by the
        # streamer (pcm_path), so nothing is synthesized on this thread; a cue
        # converts its pre-recorded WAV once; only an ad-hoc queue_info() still
        # pays for synthesis here.
        pcm_data = None
        src = "synth"
        if task.pcm_bytes is not None:
            pcm_data = task.pcm_bytes
            src = "word-cache"
        else:
            pcm = task.pcm_path
            if pcm is None:
                pcm = (self._ensure_pcm(task.wav_path) if task.wav_path
                       else self._render_pcm(task.text))
            if pcm:
                try:
                    with open(pcm, "rb") as f:
                        pcm_data = f.read()
                except OSError:
                    pcm_data = None

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

        # Interrupted before it could be heard → roll the cooldown back, so the
        # user's next press can say the same thing rather than being silently
        # suppressed by an announcement that never actually reached them.
        if task.label and self._interrupt.is_set():
            with self._cd_lock:
                if prev_cd is None:
                    self._cooldown_map.pop(task.label, None)
                else:
                    self._cooldown_map[task.label] = prev_cd

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

        with _codec():
            try:
                player = maix_audio.Player()
                try:
                    from config import cfg as _cfg
                    vol = _cfg.AUDIO_VOLUME
                except Exception:
                    vol = 80
                # Hardware volume where it exists, sample scaling where it does
                # not. MaixPy 4.5.1 raises "Not implemented" here, which used to
                # be swallowed silently — leaving audio_volume as a number the
                # UI showed and the speaker ignored. (The old fallback branch
                # called volume() AGAIN, so the retry escaped this try block and
                # killed every playback: the device went completely silent.)
                pcm_data = set_player_volume(player, vol, pcm_data)
                audio_s = len(pcm_data) / _PCM_BYTES_S

                def _abort() -> bool:
                    """True once a higher-priority task (or shutdown) wants the slot.

                    Dropping our reference to `player` on return is what actually
                    silences the codec — Player has no stop() in MaixPy 4.5.1, so
                    the destructor is the hard stop.
                    """
                    if not (self._interrupt.is_set() or self._stop.is_set()):
                        return False
                    try:
                        player.stop()
                    except AttributeError:
                        pass          # no stop() on this build — destructor handles it
                    except Exception:
                        pass
                    return True

                # Feed the driver in sub-limit chunks, paced to the playback rate.
                # See _PLAY_CHUNK_BYTES: one oversized write silently loses
                # everything past 512 KiB, which halved every long description.
                _pc0 = time.monotonic()
                written = 0
                for off in range(0, len(pcm_data), _PLAY_CHUNK_BYTES):
                    chunk = pcm_data[off:off + _PLAY_CHUNK_BYTES]
                    player.play(bytes(chunk))
                    written += len(chunk)
                    # Stay roughly one chunk ahead of the play head: enough buffer
                    # that playback never starves (no gap between chunks), little
                    # enough that the ring buffer never overflows.
                    target = written / _PCM_BYTES_S - _PLAY_CHUNK_S
                    while True:
                        if _abort():
                            return True
                        slack = target - (time.monotonic() - _pc0)
                        if slack <= 0:
                            break
                        time.sleep(min(0.02, slack))

                _play_call_s = time.monotonic() - _pc0

                # Whatever is still buffered has to drain before we free the slot.
                residual_s = residual_playback_wait_s(len(pcm_data), _play_call_s)
                if audio_s > 2.0:
                    self.logger.info(
                        f"[scene-timing] play() fed={_play_call_s * 1000:.0f}ms "
                        f"audio={audio_s * 1000:.0f}ms residual={residual_s * 1000:.0f}ms "
                        f"chunks={-(-len(pcm_data) // _PLAY_CHUNK_BYTES)}",
                        module="AudioMgr")
                deadline = time.monotonic() + residual_s

                while time.monotonic() < deadline:
                    if _abort():
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

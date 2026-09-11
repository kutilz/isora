"""
Hybrid TTS: pre-generated WAV cache first, cloud synthesis fallback.

Two cloud backends, both cached on disk by text hash:

  gtts    mp3 from Google Translate. Free, but the round-trip is slow AND
          erratic (measured on-device for one ~110-char sentence: 1.9 s to
          6.6 s, occasionally an outright failure), and the mp3 still has to be
          decoded + resampled by a spawned ffmpeg, a flat 1.2-1.8 s on top.

  openai  /v1/audio/speech with response_format=pcm. Returns RAW 24 kHz audio,
          so there is no mp3 and no ffmpeg at all — just an audioop upsample to
          the 48 kHz the MaixCAM codec plays, ~70 ms. Measured 1.9-2.4 s to
          first byte and ~3.3 s total, i.e. both faster and far steadier.
          Not the default: its voices read Indonesian with an English accent
          (gpt-4o-mini-tts plus `instructions` is the only version worth
          auditioning). Raw PCM is also ~5x more bytes on the wire than an mp3,
          which on a phone-hotspot link eats back much of what it saves.

Lookup order:
  1. Check tts_cache_dir for the rendered file  →  immediate playback
  2. Synthesize online                          →  cache + play
  3. Import error / network timeout             →  return None (silent fallback)

Thread-safe: concurrent synthesis of the SAME text is serialized, so two
callers can't race to write one cache file. Different texts synthesize in
parallel — the lock used to be a single global one, which quietly made every
background word-warm block the scene description the user was waiting on
(measured: a foreground synth stuck ~8 s behind a warm queue that normally
costs ~2 s).
"""

import os
import hashlib
import threading
from typing import Optional

# key → lock, created on demand. Guarded by _locks_lock.
_MAX_LOCKS = 256
_locks: dict = {}
_locks_lock = threading.Lock()


def _lock_for(key: str) -> threading.Lock:
    with _locks_lock:
        lk = _locks.get(key)
        if lk is None:
            lk = _locks[key] = threading.Lock()
        # The cache is pruned to _MAX_ENTRIES, so this dict is bounded in
        # practice by how many distinct utterances one session speaks; drop the
        # oldest keys if a long-running device ever wanders past that.
        if len(_locks) > _MAX_LOCKS:
            for stale in list(_locks)[:len(_locks) - _MAX_LOCKS]:
                if stale != key and not _locks[stale].locked():
                    del _locks[stale]
        return lk


def _key(text: str) -> str:
    return hashlib.md5(text.lower().strip().encode("utf-8")).hexdigest() + ".wav"


def get_or_synthesize(
    text: str,
    cache_dir: str = "/root/audio/tts_cache",
    lang: str = "id",
    timeout_s: float = 8.0,
) -> Optional[str]:
    """
    Return a local WAV path for text.
    Creates cache_dir if needed. Returns None on synthesis failure.
    """
    if not text or not text.strip():
        return None

    os.makedirs(cache_dir, exist_ok=True)
    key = _key(text)
    path = os.path.join(cache_dir, key)

    if os.path.exists(path):
        return path

    with _lock_for(key):
        if os.path.exists(path):  # re-check after acquiring lock
            return path
        result = _synthesize(text, path, lang, timeout_s)
        if result:
            _prune_cache(cache_dir)
        return result


# Scene descriptions are near-unique, so this cache mostly accumulates one-off
# entries rather than hitting. Each entry is a small .wav (gTTS mp3) plus a much
# larger .pcm sibling written by AudioManager._ensure_pcm. On a 128 MB device
# with limited flash that grows unbounded, so cap it: keep the most recently
# synthesized MAX_ENTRIES utterances (enough for "repeat last result" and any
# real repeats), deleting the oldest wav+pcm pairs beyond that.
_MAX_ENTRIES = 120


def _prune_cache(cache_dir: str, max_entries: int = _MAX_ENTRIES) -> None:
    """Keep the `max_entries` most recent utterances; delete every older one.

    Prunes by ENTRY, not by file: a gTTS utterance is a .wav plus the .pcm
    AudioManager derived from it, an OpenAI one is a lone .o.pcm. Counting raw
    files would let a cache of pure OpenAI entries grow without bound, which on
    a board with ~4 MB free is how the flash fills up.
    """
    try:
        entries: dict = {}
        for f in os.listdir(cache_dir):
            if f.endswith(".o.pcm"):
                stem = f[: -len(".o.pcm")]
            elif f.endswith(".wav") or f.endswith(".pcm"):
                stem = os.path.splitext(f)[0]
            else:
                continue
            path = os.path.join(cache_dir, f)
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            slot = entries.setdefault(stem, [mtime, []])
            slot[0] = max(slot[0], mtime)
            slot[1].append(path)
        if len(entries) <= max_entries:
            return
        oldest = sorted(entries.values(), key=lambda e: e[0])
        for _mtime, paths in oldest[: len(entries) - max_entries]:
            for victim in paths:
                try:
                    os.remove(victim)
                except OSError:
                    pass
    except OSError:
        pass


def _synthesize(text: str, out_path: str, lang: str, timeout_s: float) -> Optional[str]:
    """Render `text` to `out_path` via gTTS, giving up after `timeout_s`.

    The write goes to a temp file that is only renamed into place once gTTS has
    returned. It has to: .save() streams the mp3 out progressively and the
    worker is a daemon we ABANDON on timeout rather than kill, so writing
    straight to out_path left a half-written mp3 behind that the next lookup
    happily treated as a cache hit — the description would then play, and cut
    off mid-word, with nothing in the logs to explain it.
    """
    try:
        from gtts import gTTS
    except ImportError:
        return None

    result: list = [None]
    tmp = "%s.%d.part" % (out_path, threading.get_ident())

    def _work():
        try:
            gTTS(text=text, lang=lang, slow=False).save(tmp)
            os.replace(tmp, out_path)
            result[0] = out_path
        except Exception:
            pass
        finally:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass

    t = threading.Thread(target=_work, daemon=True)
    t.start()
    t.join(timeout=timeout_s)
    return result[0]


# ─── OpenAI TTS backend (raw PCM, no ffmpeg) ──────────────────────────────────

_OPENAI_TTS_URL  = "https://api.openai.com/v1/audio/speech"
_OPENAI_PCM_RATE = 24000          # what response_format="pcm" returns
_PLAY_RATE       = 48000          # what the MaixCAM codec plays


def _upsample_2x(raw: bytes) -> bytes:
    """24 kHz s16le mono → 48 kHz. audioop is C-fast (~70 ms for 8 s of audio).

    audioop is deprecated (gone in 3.13; the device runs 3.11), so fall back to
    a plain sample doubling. For an exact 2x ratio that is a zero-order hold —
    a shade harsher than ratecv's interpolation, but correct, and it keeps the
    device speaking on a Python that dropped the module.
    """
    try:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            import audioop
        return audioop.ratecv(raw, 2, 1, _OPENAI_PCM_RATE, _PLAY_RATE, None)[0]
    except Exception:
        import array
        src = array.array("h")
        src.frombytes(raw[:len(raw) - (len(raw) % 2)])
        out = array.array("h", bytes(len(src) * 4))
        out[0::2] = src
        out[1::2] = src
        return out.tobytes()


def get_or_synthesize_pcm(
    text: str,
    api_key: str,
    cache_dir: str = "/root/audio/tts_cache",
    model: str = "gpt-4o-mini-tts",
    voice: str = "alloy",
    instructions: str = "",
    timeout_s: float = 15.0,
) -> Optional[str]:
    """Return a path to ready-to-play 48 kHz s16le PCM for `text`, or None.

    Cached under a distinct `.o.pcm` name so flipping tts_provider never plays
    one backend's cache in the other's voice.
    """
    if not text or not text.strip() or not api_key:
        return None

    os.makedirs(cache_dir, exist_ok=True)
    # Voice/model/instructions are part of the identity of the rendering: change
    # any of them and the cached audio is the wrong voice, not a stale one.
    key = _key(f"{model}|{voice}|{instructions}|{text}")[:-4] + ".o.pcm"
    path = os.path.join(cache_dir, key)
    if os.path.exists(path):
        return path

    with _lock_for(key):
        if os.path.exists(path):
            return path
        try:
            import json
            import urllib.request
            payload = {
                "model":           model,
                "input":           text,
                "voice":           voice,
                "response_format": "pcm",
            }
            # tts-1/tts-1-hd reject `instructions`; only the gpt-4o-mini-tts
            # family can be steered on accent and delivery.
            if instructions and model.startswith("gpt-"):
                payload["instructions"] = instructions
            body = json.dumps(payload).encode()
            req = urllib.request.Request(
                _OPENAI_TTS_URL, data=body, method="POST",
                headers={"Content-Type":  "application/json",
                         "Authorization": f"Bearer {api_key}"},
            )
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                raw = resp.read()
        except Exception:
            return None
        if not raw:
            return None
        # Write via a temp file: a half-written .pcm left by a power cut would
        # otherwise be cached forever and played as a truncated sentence.
        tmp = path + ".part"
        try:
            with open(tmp, "wb") as f:
                f.write(_upsample_2x(raw))
            os.replace(tmp, path)
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass
            return None
        _prune_cache(cache_dir)
        return path

"""
Hybrid TTS: pre-generated WAV cache first, cloud gTTS synthesis fallback.

Lookup order:
  1. Check tts_cache_dir for {md5(text)}.wav  →  immediate playback
  2. Synthesize via gTTS (Indonesian, online)  →  cache + play
  3. Import error / network timeout            →  return None (silent fallback)

Thread-safe: concurrent synthesis for the same text is serialized by _lock.
"""

import os
import hashlib
import threading
from typing import Optional

_lock = threading.Lock()


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
    path = os.path.join(cache_dir, _key(text))

    if os.path.exists(path):
        return path

    with _lock:
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
    try:
        wavs = [
            os.path.join(cache_dir, f)
            for f in os.listdir(cache_dir)
            if f.endswith(".wav")
        ]
        if len(wavs) <= max_entries:
            return
        wavs.sort(key=lambda p: os.path.getmtime(p))  # oldest first
        for wav in wavs[: len(wavs) - max_entries]:
            for victim in (wav, os.path.splitext(wav)[0] + ".pcm"):
                try:
                    os.remove(victim)
                except OSError:
                    pass
    except OSError:
        pass


def _synthesize(text: str, out_path: str, lang: str, timeout_s: float) -> Optional[str]:
    try:
        from gtts import gTTS
    except ImportError:
        return None

    result: list = [None]

    def _work():
        try:
            gTTS(text=text, lang=lang, slow=False).save(out_path)
            result[0] = out_path
        except Exception:
            try:
                if os.path.exists(out_path):
                    os.remove(out_path)  # cleanup partial file
            except OSError:
                pass

    t = threading.Thread(target=_work, daemon=True)
    t.start()
    t.join(timeout=timeout_s)
    return result[0]

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
        return _synthesize(text, path, lang, timeout_s)


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

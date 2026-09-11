"""Per-word TTS cache for context-mode scene descriptions.

The measured bottleneck is the gTTS network round-trip (8-11s, often timing
out on the device's wifi). Scene descriptions are near-unique as *sentences*
but reuse a small, recurring Indonesian *vocabulary*, so caching audio per word
lets a fully-seen sentence play with ZERO network — instant — and the cache
warms as the device is used.

Hard rule ("jangan sampe ompong"): a word is NEVER dropped. If any word lacks
cached audio we speak the whole sentence in one gTTS call (complete, no gap)
and warm the missing words in the background for next time.

This module is the pure decision layer; synthesis and playback are injected so
it unit-tests with no network or hardware.
"""

import os
import hashlib
import struct
import threading
import re
from collections import namedtuple

# How to render one utterance.
#   mode="concat"          -> play word_paths back-to-back (zero network)
#   mode="synth_sentence"  -> speak the whole text via gTTS (a word was missing)
# `missing` lists words to warm in the background regardless of mode — it is a
# WARM LIST, not a miss count: when the max_words cap fires it holds every token
# even on a full cache hit. `cached_count` is the honest hit count for telemetry.
Plan = namedtuple("Plan", ["mode", "word_paths", "missing", "cached_count"])
Plan.__new__.__defaults__ = (0,)

# Indonesian scene text is ASCII; split on word chars, drop punctuation/case.
# A hyphenated token like "kiri-atas" splits into "kiri","atas" — fine, each is
# cached independently and both are common.
_WORD_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list:
    """Lowercase + punctuation-stripped word tokens, used as cache keys."""
    return _WORD_RE.findall((text or "").lower())


def plan_utterance(text: str, lookup, max_words: int = 0) -> Plan:
    """Decide how to render `text`. `lookup(word) -> path|None` resolves a word
    to its cached audio. If every word resolves we concatenate (instant, no
    network); if any is missing we speak the whole sentence (no ompong).

    `max_words` caps concat to short/recurring phrases: past that length we go
    straight to synth_sentence even on a full cache hit. A sentence spliced
    from independently-synthesized words loses sentence-level prosody (pitch,
    stress, connected speech) — each extra seam makes that worse, no matter
    how smooth the seam itself is — so long free-form text (e.g. "detail"
    scene descriptions) sounds better as one fluent gTTS render. Words still
    get reported for background warming either way, so short-phrase reuse
    elsewhere still benefits. 0 disables the cap.
    """
    toks = tokenize(text)
    if max_words > 0 and len(toks) > max_words:
        seen = set()
        deduped = [w for w in toks if not (w in seen or seen.add(w))]
        # The cap fires on FULL cache hits too, so `missing` here says nothing
        # about how warm the cache is. Count the real hits separately or the
        # dashboard reports a fully-warm cache as 0-cached on every long
        # description — the exact metric used to judge whether caching works.
        return Plan("synth_sentence", [], deduped,
                    sum(1 for w in toks if lookup(w)))
    paths = []
    missing = []
    for w in toks:
        p = lookup(w)
        if p:
            paths.append(p)
        else:
            missing.append(w)
    if missing:
        seen = set()
        deduped = [w for w in missing if not (w in seen or seen.add(w))]
        return Plan("synth_sentence", [], deduped, len(paths))
    return Plan("concat", paths, [], len(paths))


class WordCache:
    """Filesystem store of per-word PCM audio, keyed by the normalised word.

    lookup() returns a path only for a non-empty file, so a silent/half-written
    entry can never sneak a gap into a concatenated sentence.
    """

    def __init__(self, cache_dir: str):
        self.cache_dir = cache_dir
        self._lock = threading.Lock()
        try:
            os.makedirs(cache_dir, exist_ok=True)
        except OSError:
            pass

    def _norm(self, word: str) -> str:
        toks = tokenize(word)
        return toks[0] if toks else ""

    def path_for(self, word: str) -> str:
        key = hashlib.md5(self._norm(word).encode("utf-8")).hexdigest()
        return os.path.join(self.cache_dir, key + ".pcm")

    def lookup(self, word: str):
        """Return the cached PCM path for `word`, or None if not warmed."""
        if not self._norm(word):
            return None
        p = self.path_for(word)
        try:
            if os.path.getsize(p) > 0:
                return p
        except OSError:
            pass
        return None

    def count(self) -> int:
        """Number of warmed words currently cached (non-empty .pcm files).

        Surfaced to the /buttons dashboard so the operator can watch the cache
        grow as the device is used ("makin sering dipake makin banyak data").
        """
        try:
            return sum(
                1 for name in os.listdir(self.cache_dir)
                if name.endswith(".pcm")
                and os.path.getsize(os.path.join(self.cache_dir, name)) > 0
            )
        except OSError:
            return 0

    def store(self, word: str, pcm_bytes: bytes) -> bool:
        """Persist `word`'s PCM. Refuses empty audio (would be a silent gap)."""
        if not self._norm(word) or not pcm_bytes:
            return False
        p = self.path_for(word)
        try:
            with self._lock:
                tmp = p + ".tmp"
                with open(tmp, "wb") as f:
                    f.write(pcm_bytes)
                os.replace(tmp, p)   # atomic: readers never see a partial file
            return True
        except OSError:
            return False


def concat_pcm(paths, read_fn, gap_bytes: bytes = b""):
    """Join per-word PCM blobs into one, in order, with an optional silence gap
    between words. `read_fn(path) -> bytes|None`. Returns None if ANY word's
    audio can't be read — so the caller falls back rather than play a gappy clip.
    """
    out = bytearray()
    for p in paths:
        b = read_fn(p)
        if not b:
            return None
        if out and gap_bytes:
            out += gap_bytes
        out += b
    return bytes(out)


def trim_silence(pcm: bytes, threshold: int = 600, margin_samples: int = 0) -> bytes:
    """Trim leading/trailing near-silence from s16le-mono PCM.

    Each isolated gTTS word carries head/tail silence; concatenating those makes
    speech sound staccato. Trimming removes the silence (keeping `margin_samples`
    on each side) so words sit close together. All-silence input is returned
    unchanged (never nuke a word to nothing — that would be ompong).
    """
    n = len(pcm) // 2
    if n == 0:
        return pcm
    samples = memoryview(pcm).cast("h")  # signed 16-bit view, no copy
    first = None
    last = None
    for i in range(n):
        if abs(samples[i]) > threshold:
            if first is None:
                first = i
            last = i
    if first is None:
        return pcm  # all silence
    start = max(0, first - margin_samples)
    end = min(n, last + 1 + margin_samples)
    return pcm[start * 2:end * 2]


def _crossfade_join(prev: bytearray, nxt: bytes, overlap_samples: int) -> bytearray:
    """Blend `overlap_samples` samples at the seam between `prev` (accumulated
    so far) and `nxt` (next word), linearly ramping from prev's tail to nxt's
    head instead of hard-cutting either side.

    A hard cut leaves an abrupt amplitude jump at the seam — audible as a
    click/pop — because the two words were synthesized independently and
    don't share a waveform phase. Blending removes that discontinuity. Reads
    via struct.unpack_from (not a memoryview) so `prev` can be safely resized
    afterwards. Shrinks to whatever overlap both sides can actually supply,
    so a very short cached word never underflows.
    """
    n = min(overlap_samples, len(prev) // 2, len(nxt) // 2)
    if n <= 0:
        prev += nxt
        return prev
    a_start = len(prev) // 2 - n
    a_tail = struct.unpack_from("<%dh" % n, prev, a_start * 2)
    b_head = struct.unpack_from("<%dh" % n, nxt, 0)
    blended = bytearray()
    for i in range(n):
        t = (i + 1) / (n + 1)
        s = a_tail[i] * (1 - t) + b_head[i] * t
        s = max(-32768, min(32767, round(s)))
        blended += struct.pack("<h", s)
    del prev[a_start * 2:]
    prev += blended
    prev += nxt[n * 2:]
    return prev


def assemble_words(word_blobs, gap_samples: int = 0,
                   trim_threshold: int = 0, trim_margin_samples: int = 0) -> bytes:
    """Concatenate per-word PCM into one utterance.

    - trim_threshold > 0 trims each word's silence first (smoother).
    - gap_samples > 0 inserts that many silent samples between words.
    - gap_samples < 0 crossfades adjacent words over |gap_samples| samples at
      each seam (see _crossfade_join) — the "negative gap" that tightens
      run-on words AND smooths the seam, instead of just hard-cutting it.
    """
    out = bytearray()
    for b in word_blobs:
        if not b:
            continue
        if trim_threshold > 0:
            b = trim_silence(b, trim_threshold, trim_margin_samples)
        if not out:
            out += b
        elif gap_samples >= 0:
            out += b"\x00\x00" * gap_samples
            out += b
        else:
            out = _crossfade_join(out, b, -gap_samples)
    return bytes(out)

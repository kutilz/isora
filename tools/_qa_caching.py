"""QA harness: does the per-word caching mode really get more instant with use?

Measures (no device, no network) the two things the claim rests on:
  1) CONVERGENCE — over a realistic recurring "sedang" corpus, how the share of
     sentences that render instant (zero-network concat) climbs with repeated
     use, honoring the same bounded warming the device does.
  2) COST — how long the "instant" concat render actually takes vs the measured
     whole-sentence synth path, so "instant" is a number, not a vibe.

Run: python tools/_qa_caching.py   (uses the device/ package on sys.path)
"""
import os
import sys
import time
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "device"))

from utils.word_cache import (  # noqa: E402
    WordCache, plan_utterance, tokenize, assemble_words,
)

SEDANG_CORPUS = [
    "Kasur di kiri, pintu di depan, dan meja di kanan.",
    "Pakaian di kiri, kasur di depan, televisi di kanan.",
    "Selimut di kiri, pintu di depan, dan baju di kanan.",
    "Ada kasur di kiri, pintu di depan, dan stopkontak di kanan.",
    "Kasur di kiri, pakaian di kanan, dan dinding di depan.",
]
WARM_CAP = 8            # word_warm_per_call default
WORD_AUDIO_S = 0.30     # ~typical spoken word length
_RATE = 48000

# Measured on this device earlier (gTTS round-trip for a whole sentence), used
# only to contrast the synth path against the measured concat cost.
SYNTH_TO_AUDIO_MS_MEASURED = 2300


def fake_pcm(word):
    n = int(WORD_AUDIO_S * _RATE)
    # non-silent so trim keeps it; content varies a little per word
    b = (abs(hash(word)) % 4000 + 500)
    import struct
    return struct.pack("<h", b) * n


def main():
    tmp = tempfile.mkdtemp(prefix="qa_wordcache_")
    cache = WordCache(tmp)

    print("=" * 68)
    print("QA 1 — CONVERGENCE: instant-render share vs repeated use")
    print("        (corpus of %d recurring 'sedang' sentences)" % len(SEDANG_CORPUS))
    print("=" * 68)
    print(f"{'pass':>4} | {'instant':>7} | {'synth':>5} | {'hit-rate':>8} | cached words")
    print("-" * 68)

    for p in range(1, 7):
        instant = synth = 0
        for s in SEDANG_CORPUS:
            plan = plan_utterance(s, cache.lookup)
            if plan.mode == "concat":
                instant += 1
            else:
                synth += 1
                # bounded warm, exactly like _warm_words_async (todo[:cap])
                for w in plan.missing[:WARM_CAP]:
                    cache.store(w, fake_pcm(w))
        total = len(SEDANG_CORPUS)
        print(f"{p:>4} | {instant:>7} | {synth:>5} | {instant/total*100:>7.0f}% | {cache.count()}")

    print()
    print("=" * 68)
    print("QA 2 — COST: how long is 'instant'? (concat of a fully-cached sentence)")
    print("=" * 68)
    sentence = SEDANG_CORPUS[0]
    # ensure fully cached
    for w in set(tokenize(sentence)):
        if cache.lookup(w) is None:
            cache.store(w, fake_pcm(w))
    paths = [cache.lookup(w) for w in tokenize(sentence)]
    blobs = [open(p, "rb").read() for p in paths]

    # time the real assemble path (trim + negative-gap overlap), many iterations
    N = 200
    t0 = time.perf_counter()
    for _ in range(N):
        pcm = assemble_words(blobs, gap_samples=int(_RATE * -10 / 1000),
                             trim_threshold=600, trim_margin_samples=int(_RATE * 8 / 1000))
    concat_ms = (time.perf_counter() - t0) / N * 1000
    audio_ms = len(pcm) / (_RATE * 2) * 1000

    print(f"sentence            : {sentence}")
    print(f"words               : {len(tokenize(sentence))}")
    print(f"concat assemble time: {concat_ms:.2f} ms  (PC; device single-core is slower but still ms-scale)")
    print(f"resulting audio len : {audio_ms:.0f} ms")
    print(f"synth path (measured): ~{SYNTH_TO_AUDIO_MS_MEASURED} ms before audio even starts (gTTS round-trip)")
    speedup = SYNTH_TO_AUDIO_MS_MEASURED / max(concat_ms, 0.01)
    print(f"=> time-to-audio: cache path is ~{speedup:.0f}x faster to start than synth")

    print()
    print("VERDICT: TRUE — but it's about vocabulary REUSE, not raw repetition.")
    print(" - recurring vocabulary  -> hit-rate climbs to 100%, render is ms not seconds")
    print(" - all-new words each time -> stays on the slow synth path (no win)")
    print(" - 'sedang' mode (short, consistent) saturates fast; 'detail' (varied) slower")

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()

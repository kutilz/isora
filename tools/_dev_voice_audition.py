"""Play candidate TTS voices through the device speaker, back to back.

Each sample announces its own number first, so the listener can identify a
voice by ear without watching a terminal — the whole point is judging how the
voice reads Indonesian, not reading about it.
"""
import sys, os, time
sys.path.insert(0, "/root/isora")
from config import cfg
from utils.tts import get_or_synthesize_pcm

NUM = {1: "Suara satu.", 2: "Suara dua.", 3: "Suara tiga.", 4: "Suara empat.",
       5: "Suara lima.", 6: "Suara enam."}
BODY = ("Di depan ada seorang pria berkacamata berdiri dekat meja komputer. "
        "Di sebelah kanan Anda ada kursi kosong, jalur di depan aman.")
INSTR = ("Bacakan dalam Bahasa Indonesia dengan logat Indonesia yang natural, "
         "tenang, dan jelas. Jangan memakai aksen Inggris.")
VOICES = sys.argv[1:] or ["alloy", "nova", "sage", "coral"]
KEY = cfg.OPENAI_API_KEY

from maix import audio as ma


# Reuse the app's real pacing constants. The first version of this script slept
# for a whole chunk's DURATION after each write, so the codec ring buffer ran
# dry before the next one arrived — a gap every 2 s. It made every candidate
# sound choppy and therefore quiet, and nearly got a perfectly good voice
# rejected. The rule is to stay one chunk AHEAD of the play head, not one
# chunk behind it.
from core.audio_manager import (_PLAY_CHUNK_BYTES, _PCM_BYTES_S,  # noqa: E402
                                _PLAY_CHUNK_S)


def play(data):
    p = ma.Player()
    try:
        p.volume(cfg.AUDIO_VOLUME)
    except Exception:
        pass
    t0 = time.monotonic()
    written = 0
    for off in range(0, len(data), _PLAY_CHUNK_BYTES):
        chunk = data[off:off + _PLAY_CHUNK_BYTES]
        p.play(bytes(chunk))
        written += len(chunk)
        target = written / _PCM_BYTES_S - _PLAY_CHUNK_S
        while True:
            slack = target - (time.monotonic() - t0)
            if slack <= 0:
                break
            time.sleep(min(0.02, slack))
    while time.monotonic() - t0 < len(data) / _PCM_BYTES_S + 0.15:
        time.sleep(0.02)
    del p


for i, v in enumerate(VOICES, 1):
    text = "%s %s" % (NUM.get(i, "Suara %d." % i), BODY)
    t0 = time.monotonic()
    p = get_or_synthesize_pcm(text, api_key=KEY, cache_dir="/tmp/voices",
                              model="gpt-4o-mini-tts", voice=v,
                              instructions=INSTR, timeout_s=60)
    dt = (time.monotonic() - t0) * 1000
    if not p:
        print("  %d. %-8s FAILED (%.0fms)" % (i, v, dt)); continue
    data = open(p, "rb").read()
    print("  %d. %-8s render=%6.0fms  audio=%.1fs  -> playing now" % (
        i, v, dt, len(data) / 96000.0))
    sys.stdout.flush()
    play(data)
    time.sleep(1.5)          # clear gap between candidates
print("done")

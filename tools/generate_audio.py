"""
Audio Generator — PC-side script untuk pre-generate semua file WAV.
Jalankan sekali di laptop sebelum deploy ke MaixCAM.

Requires: pip install gtts
Output:   ../audio/*.wav

Usage:
    python tools/generate_audio.py --from-wordlist
    python tools/generate_audio.py --legacy
    python tools/generate_audio.py --lang id --output ../audio
    python tools/generate_audio.py --dry-run --from-wordlist
"""

import os
import re
import sys
import time
import argparse

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "audio")
WORDLIST_DEFAULT = os.path.join(OUTPUT_DIR, "AuralAI_Audio_Wordlist.md")

# Baris: namafile.wav … → "teks untuk TTS"
_WORDLIST_LINE = re.compile(r"^(\S+\.wav)\s+→\s*\"(.*)\"\s*$")

# ─── Label & Posisi ───────────────────────────────────────────────────────────

OBJECTS = {
    "person":     "orang",
    "motorcycle": "motor",
    "car":        "mobil",
    "bicycle":    "sepeda",
    "bus":        "bus",
    "truck":      "truk",
    "dog":        "anjing",
    "cat":        "kucing",
    "chair":      "kursi",
    "bottle":     "botol",
    "handbag":    "tas",
    "backpack":   "ransel",
}

POSITIONS = {
    "left":         "di sebelah kiri",
    "right":        "di sebelah kanan",
    "center":       "di depan",
    "top_left":     "di kiri atas",
    "top_right":    "di kanan atas",
    "top":          "di atas",
    "bottom":       "di bawah",
    "bottom_left":  "di kiri bawah",
    "bottom_right": "di kanan bawah",
}

SYSTEM_EVENTS = {
    # Onboarding / status cues for the screen-less device. Keys match the
    # AudioManager._find_wav safe-name of the spoken text, so these play
    # offline (no gTTS call) at boot and on button-acknowledge.
    "auralai_siap_digunakan":       "AuralAI siap digunakan.",
    "baik_sudah_paham":             "Baik, sudah paham.",
    # Keys must match orchestrator.switch_mode's queue_system(f"mode_{new_mode}"),
    # i.e. mode_explorer / mode_context / mode_qris (NOT *_aktif) so _find_wav
    # resolves system_mode_<x>.wav instead of TTS-speaking the literal key.
    "mode_explorer":                "mode penjelajah aktif",
    "mode_context":                 "mode konteks aktif",
    "mode_qris":                    "mode scan bayar aktif",
    "sedang_menganalisis":          "sedang menganalisis",
    "masih_memproses":              "masih memproses",
    "memindai_kode_pembayaran":     "memindai kode pembayaran",
    "selesai":                      "selesai",
    "koneksi_gagal":                "koneksi gagal",
    "baterai_lemah":                "baterai lemah",
    "tidak_ada_deteksi":            "tidak ada objek terdeteksi",
    "api_tidak_tersedia":           "API tidak tersedia",
    "gagal_menganalisis":           "gagal menganalisis",
    "gagal_memindai":               "gagal memindai, coba lagi",
}


# ─── Non-speech chimes (synthesized offline, no network/gTTS) ─────────────────
# Each chime is a list of (frequency_Hz, duration_ms) tone segments. Played as
# instant tactile/state feedback by AudioManager.queue_cue (see device side).
# Synthesized with numpy + stdlib wave — no downloads, no licensing.
_CHIME_RATE = 48000        # Hz, mono s16 (matches AudioManager PCM target)
_CHIME_AMP  = 0.30         # peak amplitude (0..1), gentle on a small speaker

CHIMES = {
    "chime_press":   [(1200, 60)],                       # soft tick — press ack
    "chime_capture": [(660, 80), (990, 90)],             # rising — capture started
    "chime_success": [(660, 70), (880, 70), (1320, 110)],# rising arpeggio — done
    "chime_error":   [(440, 120), (330, 150)],           # descending — failed
    "chime_ready":   [(523, 90), (659, 90), (784, 130)], # C-E-G — boot ready
    "chime_mode":    [(880, 70)],                        # neutral blip — mode switch
}


def _render_chime(segments):
    """Render (freq, dur_ms) segments → int16 numpy samples with click-free envelope."""
    import numpy as np
    out = []
    for freq, dur_ms in segments:
        n = int(_CHIME_RATE * dur_ms / 1000.0)
        t = np.arange(n) / _CHIME_RATE
        wave_f = np.sin(2 * np.pi * freq * t)
        # Linear attack/decay envelope (~5 ms each, clamped) to avoid clicks.
        ramp = min(int(_CHIME_RATE * 0.005), n // 2) or 1
        env = np.ones(n)
        env[:ramp]  = np.linspace(0.0, 1.0, ramp)
        env[-ramp:] = np.linspace(1.0, 0.0, ramp)
        out.append(wave_f * env)
    sig = np.concatenate(out) if out else np.zeros(0)
    return (sig * _CHIME_AMP * 32767.0).astype("<i2")


def synth_chimes(output_dir, dry_run=False):
    """Generate all CHIMES as 48 kHz mono 16-bit WAV in output_dir."""
    try:
        import numpy  # noqa: F401
    except ImportError:
        print("ERROR: numpy tidak terinstall. Jalankan: pip install numpy")
        sys.exit(1)
    import wave

    os.makedirs(output_dir, exist_ok=True)
    print(f"Akan generate {len(CHIMES)} chime ke: {output_dir}\n")

    generated = 0
    for name, segments in CHIMES.items():
        out_path = os.path.join(output_dir, f"{name}.wav")
        if dry_run:
            total_ms = sum(d for _, d in segments)
            print(f"  DRY   {name}.wav -> {segments} ({total_ms} ms)")
            continue
        samples = _render_chime(segments)
        with wave.open(out_path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(_CHIME_RATE)
            w.writeframes(samples.tobytes())
        print(f"  OK    {name}.wav")
        generated += 1

    if not dry_run:
        print(f"\nSelesai! Generated {generated} chime di: {os.path.abspath(output_dir)}")
        print("Selanjutnya: upload folder audio/ ke MaixCAM di /root/audio/")


def build_audio_list():
    """Buat list semua (filename, text) yang perlu di-generate."""
    items = []

    # Object detection audio
    for obj_key, obj_id in OBJECTS.items():
        for pos_key, pos_id in POSITIONS.items():
            filename = f"obj_{obj_key}_{pos_key}.wav"
            text = f"{obj_id} {pos_id}"
            items.append((filename, text))

    # System events
    for event_key, event_text in SYSTEM_EVENTS.items():
        filename = f"system_{event_key}.wav"
        items.append((filename, event_text))

    return items


def parse_wordlist_markdown(md_path):
    """
    Baca audio/AuralAI_Audio_Wordlist.md — baris pola:
    system_ready.wav                → "AuralAI siap digunakan"
    """
    items = []
    seen = set()
    with open(md_path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            m = _WORDLIST_LINE.match(line)
            if not m:
                continue
            filename, text = m.group(1), m.group(2)
            if filename in seen:
                continue
            seen.add(filename)
            items.append((filename, text))
    return items


def generate_all(items, output_dir, lang="id", dry_run=False, delay=0.5):
    try:
        from gtts import gTTS
    except ImportError:
        print("ERROR: gTTS tidak terinstall. Jalankan: pip install gtts")
        sys.exit(1)

    os.makedirs(output_dir, exist_ok=True)

    print(f"Akan generate {len(items)} file WAV ke: {output_dir}")
    print(f"Lang: {lang} | Dry run: {dry_run}\n")

    existing = 0
    generated = 0
    failed = 0

    for i, (filename, text) in enumerate(items):
        out_path = os.path.join(output_dir, filename)

        if os.path.exists(out_path):
            print(f"  [{i+1:3d}/{len(items)}] SKIP  {filename}")
            existing += 1
            continue

        if dry_run:
            print(f"  [{i+1:3d}/{len(items)}] DRY   {filename} -> \"{text}\"")
            continue

        try:
            tts = gTTS(text=text, lang=lang, slow=False)
            tts.save(out_path)
            print(f"  [{i+1:3d}/{len(items)}] OK    {filename} -> \"{text}\"")
            generated += 1
            time.sleep(delay)  # Jeda untuk hindari rate limit
        except Exception as e:
            print(f"  [{i+1:3d}/{len(items)}] FAIL  {filename} -> {e}")
            failed += 1

    print(f"\nSelesai!")
    print(f"  Generated : {generated}")
    print(f"  Skipped   : {existing}")
    print(f"  Failed    : {failed}")
    print(f"  Total     : {len(items)}")

    if not dry_run and generated > 0:
        print(f"\nFile tersimpan di: {os.path.abspath(output_dir)}")
        print("Selanjutnya: upload folder audio/ ke MaixCAM di /root/audio/")
        print("  Gunakan: python tools/deploy.py --audio-only")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AuralAI Audio Generator (gTTS)")
    parser.add_argument("--output", default=OUTPUT_DIR, help="Output directory")
    parser.add_argument("--lang", default="id", help="Language code (default: id)")
    parser.add_argument("--delay", type=float, default=0.5, help="Delay antar request (default: 0.5s)")
    parser.add_argument("--dry-run", action="store_true", help="List saja tanpa generate")
    parser.add_argument(
        "--from-wordlist",
        nargs="?",
        const=WORDLIST_DEFAULT,
        default=None,
        metavar="PATH",
        help=f"Generate dari Markdown wordlist (default: {WORDLIST_DEFAULT})",
    )
    parser.add_argument(
        "--legacy",
        action="store_true",
        help="Pola lama: kombinasi objek×posisi + system_* pendek",
    )
    parser.add_argument(
        "--chimes",
        action="store_true",
        help="Synthesize non-speech chimes (numpy, offline) — no gTTS",
    )
    args = parser.parse_args()

    if sum(bool(x) for x in (args.legacy, args.from_wordlist, args.chimes)) > 1:
        print("ERROR: pilih salah satu --legacy / --from-wordlist / --chimes")
        sys.exit(1)

    if args.chimes:
        synth_chimes(args.output, dry_run=args.dry_run)
        sys.exit(0)

    if args.from_wordlist:
        wl_path = args.from_wordlist
        if not os.path.isfile(wl_path):
            print(f"ERROR: Wordlist tidak ditemukan: {wl_path}")
            sys.exit(1)
        audio_items = parse_wordlist_markdown(wl_path)
        print(f"Sumber wordlist: {wl_path} ({len(audio_items)} entri)\n")
    else:
        audio_items = build_audio_list()

    generate_all(
        items=audio_items,
        output_dir=args.output,
        lang=args.lang,
        dry_run=args.dry_run,
        delay=args.delay,
    )

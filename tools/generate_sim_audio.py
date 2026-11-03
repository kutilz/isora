"""
Suara simulasi — render kalimat tetap /simulasi dengan gTTS (bahasa id).

Simulasi dulu memakai Web Speech bawaan ponsel, yang di banyak HP jatuh ke suara
bahasa Inggris dan logatnya aneh. Perangkat asli memakai gTTS, jadi kalimat yang
bisa diketahui sebelumnya (objek x posisi x "dekat", sapaan, pesan sistem)
di-render di sini sekali dan diputar sebagai file. Kalimat dinamis (jawaban AI,
nama merchant QRIS) lewat /api/tts saat itu juga.

Sumber kata: web/lib/sim/constants.ts (NAV_OBJECTS + POS_PHRASE), dibaca langsung
supaya tidak ada daftar kedua yang bisa melenceng. Kalimat navigasi dipercepat
sama seperti di perangkat (generate_audio.NAV_SPEECH_RATE).

Requires: pip install gtts ; ffmpeg di PATH
Output:   web/public/audio/sim/<kunci>.mp3
          web/lib/sim/voice-manifest.json   (kunci -> teks; klien hanya memutar
                                             kunci yang ada di sini)

Usage:
    python tools/generate_sim_audio.py
    python tools/generate_sim_audio.py --dry-run     # cetak daftar kalimat saja
    python tools/generate_sim_audio.py --force       # render ulang semua
"""

import io
import os
import re
import sys
import json
import time
import argparse
import subprocess

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONSTANTS = os.path.join(ROOT, "web", "lib", "sim", "constants.ts")
MANIFEST = os.path.join(ROOT, "web", "lib", "sim", "voice-manifest.json")
OUT_DIR = os.path.join(ROOT, "web", "public", "audio", "sim")

sys.path.insert(0, os.path.dirname(__file__))
from generate_audio import NAV_SPEECH_RATE, atempo_chain  # noqa: E402

# Kalimat sistem yang diucapkan SimulasiClient / qris.ts apa adanya.
SYSTEM_PHRASES = [
    "Isora siap digunakan.",
    "Tidak ada objek yang dikenali.",
    "Belum ada kode yang terbaca.",
    "Deteksi objek belum siap.",
    "Sedang memproses.",
    "Gagal, coba lagi.",
    "Fitur ini hanya aktif pukul dua belas lima puluh sampai lima belas tiga puluh.",
    "Kode terbaca, tapi bukan kode pembayaran QRIS.",
    "Belum ada uang yang terbaca.",
    # Sama dengan money.ts:spokenNominal untuk tiap kelas model uang.
    "seribu rupiah",
    "dua ribu rupiah",
    "lima ribu rupiah",
    "sepuluh ribu rupiah",
    "dua puluh ribu rupiah",
    "lima puluh ribu rupiah",
    "seratus ribu rupiah",
]


def voice_key(text):
    """Nama file untuk satu kalimat. Harus sama persis dengan lib/sim/audio.ts:voiceKey."""
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _ts_map(source, name):
    """Ambil `export const NAME: Record<string, string> = { ... };` dari constants.ts."""
    m = re.search(r"export const " + name + r"[^=]*=\s*\{(.*?)\n\};", source, re.S)
    if not m:
        sys.exit(f"{name} tidak ditemukan di {CONSTANTS}")
    return dict(re.findall(r'^\s*"?([\w-]+)"?:\s*"([^"]+)"', m.group(1), re.M))


def nav_phrases():
    """Sama dengan constants.caption() untuk tiap objek, posisi, dan tier."""
    with open(CONSTANTS, encoding="utf-8") as f:
        src = f.read()
    objects = _ts_map(src, "NAV_OBJECTS")
    positions = _ts_map(src, "POS_PHRASE")
    out = []
    for obj in objects.values():
        for phrase in positions.values():
            for suffix in ("", " dekat"):
                out.append(f"{obj} {phrase}{suffix}".strip())
    return out


def render(text, rate, path):
    from gtts import gTTS

    buf = io.BytesIO()
    for attempt in range(4):
        try:
            gTTS(text=text, lang="id").write_to_fp(buf)
            break
        except Exception as e:  # gTTS kadang kena 429; tunggu lalu ulang
            if attempt == 3:
                raise
            print(f"        ulang ({e.__class__.__name__}), tunggu {2 ** attempt * 3} s")
            time.sleep(2 ** attempt * 3)
            buf = io.BytesIO()
    data = buf.getvalue()
    chain = atempo_chain(rate)
    if chain:
        data = subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "mp3", "-i", "pipe:0",
             "-filter:a", ",".join(chain), "-ac", "1", "-b:a", "48k", "-f", "mp3", "pipe:1"],
            input=data, capture_output=True, check=True,
        ).stdout
    if not data:
        raise RuntimeError(f"keluaran kosong: {text!r}")
    with open(path, "wb") as f:
        f.write(data)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    jobs = [(t, NAV_SPEECH_RATE) for t in nav_phrases()] + [(t, 1.0) for t in SYSTEM_PHRASES]
    manifest = {}
    for text, _ in jobs:
        manifest[voice_key(text)] = text
    if len(manifest) != len(jobs):
        sys.exit("dua kalimat menghasilkan kunci yang sama")

    if args.dry_run:
        for text, rate in jobs:
            print(f"{rate:>4}x  {voice_key(text)}.mp3  <- {text}")
        print(f"{len(jobs)} kalimat")
        return

    os.makedirs(OUT_DIR, exist_ok=True)
    made = 0
    for i, (text, rate) in enumerate(jobs, 1):
        path = os.path.join(OUT_DIR, voice_key(text) + ".mp3")
        if not args.force and os.path.exists(path) and os.path.getsize(path) > 0:
            continue
        print(f"  [{i}/{len(jobs)}] {text}")
        render(text, rate, path)
        made += 1
        time.sleep(0.3)

    # File lama yang tidak lagi diucapkan: hapus supaya tidak ikut terdeploy.
    for name in os.listdir(OUT_DIR):
        if name.endswith(".mp3") and name[:-4] not in manifest:
            os.remove(os.path.join(OUT_DIR, name))

    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")
    size = sum(os.path.getsize(os.path.join(OUT_DIR, n)) for n in os.listdir(OUT_DIR))
    print(f"{made} dirender, {len(manifest)} total, {size / 1e6:.1f} MB -> {OUT_DIR}")


if __name__ == "__main__":
    main()

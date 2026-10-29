"""
Buku audio — render versi suara Manual Book I-SORA untuk halaman web /buku.

QR di buku cetak membuka isora-smartglasses.vercel.app/buku. Teksnya ada di
web/content/buku.json (sumber tunggal); skrip ini membacanya, mengubah tiap bab
menjadi kalimat yang enak diucapkan, me-render-nya dengan gTTS (bahasa id), lalu
menyambung semuanya menjadi SATU MP3 plus penanda waktu tiap bab. Satu file,
bukan satu per bab, supaya ponsel tetap memutar sampai habis walau layar mati
(memutar file berikutnya dari JS sering diblokir saat halaman di latar).

Requires: pip install gtts ; ffmpeg di PATH
Output:   web/public/buku-audio/manual-book-isora.mp3
          web/content/buku-audio.json   (durasi + detik mulai tiap bab)

Usage:
    python tools/generate_buku_audio.py
    python tools/generate_buku_audio.py --dry-run     # cetak teks ucapan saja
"""

import io
import os
import re
import sys
import json
import time
import hashlib
import argparse
import tempfile
import subprocess

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONTENT = os.path.join(ROOT, "web", "content", "buku.json")
MARKERS = os.path.join(ROOT, "web", "content", "buku-audio.json")
OUT_DIR = os.path.join(ROOT, "web", "public", "buku-audio")
OUT_NAME = "manual-book-isora.mp3"
URL_PATH = f"/buku-audio/{OUT_NAME}"

RATE = 24000          # gTTS keluar 24 kHz mono
TEMPO = 1.1           # gTTS bahasa id agak lambat; pemutar masih bisa dipercepat
GAP_S = 1.2           # jeda hening antarbab
CACHE = os.path.join(tempfile.gettempdir(), "isora-buku-tts")

INTRO = (
    "Buku audio Isora. Kacamata pintar untuk penyandang tunanetra. "
    "Buku ini berisi tujuh belas bab. Bab satu sampai sembilan mengenalkan Isora. "
    "Bab sepuluh sampai enam belas adalah panduan pemakaian: keselamatan, tombol dan mode, "
    "mengisi daya, dan kalau ada masalah."
)

CONTACT_SAY = (
    "Email: isora o t w pimnas dua enam, et, gmail titik com. "
    "Instagram dan YouTube: isora underscore smartglasses."
)


# ─── Teks tulis → teks ucap ─────────────────────────────────────────────────

def _rupiah(m):
    n = int(m.group(1).replace(".", ""))
    if n % 1_000_000 == 0:
        return f"{n // 1_000_000} juta rupiah"
    if n % 1000 == 0:
        return f"{n // 1000} ribu rupiah"
    return f"{n} rupiah"


def speakable(s):
    """Ubah teks buku menjadi kalimat yang dibaca gTTS dengan benar."""
    s = re.sub(r"I-SORA|I-Sora", "Isora", s)          # gTTS membaca tanda hubung
    s = re.sub(r"Rp ?(\d+)–(\d+) juta", r"\1 sampai \2 juta rupiah", s)
    s = re.sub(r"Rp ?(\d+) juta", r"\1 juta rupiah", s)
    s = re.sub(r"Rp ?(\d{1,3}(?:\.\d{3})+)", _rupiah, s)
    s = re.sub(r"(\d)–(\d)", r"\1 sampai \2", s)
    s = s.replace("–", ", ")
    s = re.sub(r"(\d)×", r"\1 kali", s)
    s = s.replace("±", "sekitar ").replace("> ", "lebih dari ")
    s = s.replace("%", " persen").replace("°C", " derajat Celsius")
    s = s.replace("mAh", " miliampere jam")
    s = re.sub(r"(\d) V\b", r"\1 volt", s)
    s = re.sub(r"(\d) A\b", r"\1 ampere", s)
    s = s.replace("RISC-V", "RISC five").replace("BLE 5.0", "BLE 5")
    s = s.replace("Type-C", "type C").replace("USB-C", "USB C")
    s = re.sub(r"\b([A-Z]{2,})-([A-Z]{2,})\b", r"\1 \2", s)   # PKM-KI → PKM KI
    s = s.replace(" + ", " dan ").replace(" & ", " dan ")
    s = s.replace(" / ", " atau ").replace("/", " dan ")
    s = s.replace("(", ", ").replace(")", ",")
    s = s.replace(" = ", " untuk ")
    s = re.sub(r"[“”\"]", "", s)
    s = re.sub(r"\s+,", ",", s)
    s = re.sub(r",{2,}", ",", s)
    s = re.sub(r",\s*([.:;])", r"\1", s)
    s = re.sub(r"([.?!:])\.+", r"\1", s)
    return re.sub(r"\s{2,}", " ", s).strip()


def _sentence(s):
    s = s.strip()
    return s if s.endswith((".", "?", "!", ":")) else s + "."


def chapter_script(ch):
    """Satu bab → satu teks ucap. Tabel dibaca per baris, daftar per butir."""
    parts = [f"Bab {ch['num']}. {ch['title']}."]
    for b in ch["blocks"]:
        if "p" in b or "note" in b:
            parts.append(_sentence(b.get("p") or b["note"]))
        elif "h" in b:
            parts.append(_sentence(b["h"]))
        elif "ul" in b:
            parts += [_sentence(i) for i in b["ul"]]
        elif "ol" in b:
            parts += [f"Langkah {n}, {_sentence(t)} {_sentence(d)}"
                      for n, (t, d) in enumerate(b["ol"], 1)]
        elif "dl" in b:
            parts += [f"{_sentence(t)} {_sentence(d)}" for t, d in b["dl"]]
        elif "table" in b:
            head, rows = b["table"]["head"], b["table"]["rows"]
            for r in rows:
                if len(head) == 2:
                    parts.append(_sentence(f"{r[0]}: {r[1]}"))
                else:
                    cells = "; ".join(f"{head[i]}: {r[i]}" for i in range(1, len(head)))
                    parts.append(_sentence(f"{r[0]}. {cells}"))
        elif b.get("contact"):
            parts.append(CONTACT_SAY)
    return speakable(" ".join(parts))


# ─── Render ─────────────────────────────────────────────────────────────────

def tts_pcm(text, lang="id"):
    """gTTS → PCM s16le mono 24 kHz (sudah di-atempo). Di-cache per teks."""
    key = hashlib.sha256(f"{lang}|{TEMPO}|{text}".encode("utf-8")).hexdigest()[:20]
    path = os.path.join(CACHE, key + ".pcm")
    if os.path.exists(path) and os.path.getsize(path) > 0:
        with open(path, "rb") as f:
            return f.read()

    from gtts import gTTS
    buf = io.BytesIO()
    for attempt in range(4):
        try:
            gTTS(text=text, lang=lang, slow=False).write_to_fp(buf)
            break
        except Exception as e:  # jaringan ke Google kadang putus di ISP ini
            if attempt == 3:
                raise
            print(f"    gTTS gagal ({e}); coba lagi…")
            buf = io.BytesIO()
            time.sleep(2 + attempt * 3)

    pcm = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
         "-af", f"atempo={TEMPO}", "-f", "s16le", "-ac", "1", "-ar", str(RATE), "pipe:1"],
        input=buf.getvalue(), capture_output=True, check=True,
    ).stdout
    os.makedirs(CACHE, exist_ok=True)
    with open(path, "wb") as f:
        f.write(pcm)
    return pcm


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="cetak teks ucapan, tanpa gTTS")
    args = ap.parse_args()

    with open(CONTENT, encoding="utf-8") as f:
        book = json.load(f)

    tracks = [("intro", "Pembuka", speakable(INTRO))]
    tracks += [(ch["id"], ch["title"], chapter_script(ch)) for ch in book["chapters"]]

    if args.dry_run:
        for tid, _, text in tracks:
            print(f"── {tid}\n{text}\n")
        return

    gap = b"\x00\x00" * int(RATE * GAP_S)
    pcm = bytearray()
    markers = []
    for tid, title, text in tracks:
        print(f"  {tid}: {len(text)} huruf")
        markers.append({"id": tid, "title": title, "start": round(len(pcm) / 2 / RATE, 2)})
        pcm += tts_pcm(text)
        pcm += gap

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, OUT_NAME)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "s16le", "-ac", "1", "-ar", str(RATE), "-i", "pipe:0",
         "-c:a", "libmp3lame", "-b:a", "32k",
         "-metadata", "title=Manual Book I-SORA (buku audio)",
         "-metadata", "artist=Tim I-SORA", out],
        input=bytes(pcm), check=True,
    )
    with open(out, "rb") as f:
        version = hashlib.sha256(f.read()).hexdigest()[:10]

    duration = round(len(pcm) / 2 / RATE, 2)
    with open(MARKERS, "w", encoding="utf-8") as f:
        json.dump({
            "_comment": "Dibuat oleh tools/generate_buku_audio.py — jangan disunting tangan.",
            "src": f"{URL_PATH}?v={version}",
            "duration": duration,
            "markers": markers,
        }, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"\n✓ {out}  ({os.path.getsize(out) / 1e6:.1f} MB, {duration / 60:.1f} menit)")
    print(f"✓ {MARKERS}")


if __name__ == "__main__":
    sys.exit(main())

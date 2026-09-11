#!/usr/bin/env python3
"""
Field Mark — tandai ground-truth ke marks.jsonl (timestamp = jam device)
=======================================================================
Operator menjalankan ini lewat SSH tepat saat sebuah kejadian terjadi di lab,
sehingga analyze.py bisa mencocokkan apa-yang-seharusnya vs apa-yang-device-lihat.

Pakai jam device (time.time()) — jalankan DI device supaya sebanding dgn
recorder/driver.

Contoh (Blok A — explorer, objek masuk/keluar):
  python3 .../mark.py A1 enter person kanan 3      # orang masuk dari kanan ~3m
  python3 .../mark.py A1 move  person kanan 1      # objek sama, sekarang ~1m
  python3 .../mark.py A1 exit  person              # orang keluar frame

Contoh (Blok B — anti-spam / recovery):
  python3 .../mark.py A1 empty_start              # mulai scene kosong (diam)
  python3 .../mark.py A1 empty_end
  python3 .../mark.py A1 cover                     # lensa ditutup
  python3 .../mark.py A1 uncover
  python3 .../mark.py A1 static person tengah 2    # objek diam (uji re-announce)

Contoh (umum):
  python3 .../mark.py A1 phase "Blok A skenario 3: cahaya redup"
  python3 .../mark.py A1 note  "pantulan kaca di kanan"

Jarak (dist_m) opsional; tier (far/near) opsional di akhir. Kalau tier tidak
diisi, analyze memakai dist_m + ambang per-kelas untuk menebak tier harapan.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from _common import session_dir, append_jsonl, now, LABEL_ID  # noqa: E402

# tag yang membawa info objek (label/pos/jarak/tier)
_OBJ_TAGS = {"enter", "move", "exit", "static"}
# tag interval/penanda murni
_FLAG_TAGS = {"empty_start", "empty_end", "cover", "uncover", "phase", "note",
              "net_down", "net_up", "barge_setup"}

_VALID_POS = {"kiri", "kanan", "tengah", "depan"}


def _usage():
    print(__doc__)
    sys.exit(1)


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        _usage()

    session = args[0]
    tag = args[1].lower()
    rest = args[2:]

    ts, iso, _ = now()
    rec = {"ts": ts, "iso": iso, "kind": "mark", "tag": tag}

    if tag in _OBJ_TAGS:
        # enter/move/static: label [pos] [dist_m] [tier]
        # exit: label
        if not rest:
            print(f"[mark] tag '{tag}' butuh minimal: label", flush=True)
            sys.exit(1)
        label = rest[0].lower()
        if label not in LABEL_ID and label not in LABEL_ID.values():
            print(f"[mark] WARNING: label '{label}' bukan objek nav yang dikenal "
                  f"(lanjut saja).", flush=True)
        # normalisasi id indonesia -> english label
        inv = {v: k for k, v in LABEL_ID.items()}
        rec["label"] = inv.get(label, label)
        if tag != "exit":
            pos = rest[1].lower() if len(rest) > 1 else "tengah"
            if pos == "depan":
                pos = "tengah"
            if pos not in _VALID_POS:
                print(f"[mark] WARNING: pos '{pos}' bukan kiri/kanan/tengah.",
                      flush=True)
            rec["pos"] = pos
            # dist_m + tier opsional
            for tok in rest[2:]:
                tl = tok.lower()
                if tl in ("near", "far"):
                    rec["tier"] = tl
                else:
                    try:
                        rec["dist_m"] = float(tok)
                    except ValueError:
                        pass
    elif tag in _FLAG_TAGS:
        if rest:
            rec["text"] = " ".join(rest)
    else:
        print(f"[mark] tag tidak dikenal: '{tag}'", flush=True)
        _usage()

    path = os.path.join(session_dir(session, create=True), "marks.jsonl")
    append_jsonl(path, rec)
    print(f"[mark] {iso}  {tag}  " +
          " ".join(f"{k}={v}" for k, v in rec.items()
                   if k not in ("ts", "iso", "kind", "tag")),
          flush=True)


if __name__ == "__main__":
    main()

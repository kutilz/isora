"""
Field-benchmark shared helpers (in-situ lab testing).
=====================================================
Dipakai oleh recorder.py / mark.py / driver.py / analyze.py.

Sengaja HANYA pakai stdlib (urllib, json, time, os) — TANPA `maix`, TANPA
import device-only. Jadi:
  • recorder/driver/mark bisa jalan di device (loopback) ATAU dari PC operator.
  • analyze.py bisa jalan di mana saja (termasuk laptop) untuk mengolah hasil.

Sumber kebenaran waktu: SATU jam saja. Jalankan recorder + mark + driver SEMUA
di device (via SSH), sehingga `time.time()` mereka sebanding. Kalau dijalankan
dari PC, jamnya beda dari device — boleh untuk capture, tapi korelasi latency
antar-file jadi tidak presisi.
"""

import json
import os
import time
import urllib.request
import urllib.error

# Lokasi default sesi hasil di device.
SESSION_ROOT = os.environ.get("ISORA_FIELD_ROOT", "/root/logs/field")

DEFAULT_BASE = "http://127.0.0.1:8080"


# ─── Object / posisi maps (CERMIN dari device — jaga tetap sinkron) ───────────
# Sumber: device/core/audio_manager.py (_LABEL_ID, _POS_PHRASE) +
# device/config.py (NAV_OBJECTS). Disalin di sini supaya analyze.py tidak perlu
# import kode device. Kalau NAV_OBJECTS berubah, update juga di sini.
LABEL_ID = {
    "person": "orang", "motorcycle": "motor", "car": "mobil", "bicycle": "sepeda",
    "bus": "bus", "truck": "truk", "dog": "anjing", "cat": "kucing",
    "chair": "kursi", "bottle": "botol", "handbag": "tas", "backpack": "ransel",
}
ID_LABEL = {v: k for k, v in LABEL_ID.items()}

# Posisi horizontal kasar yang dipakai untuk ground-truth: kiri / kanan / tengah.
# Grid pos device ("kiri", "kanan-atas", "tengah", "bawah", ...) di-collapse ke
# salah satu dari tiga ini.
def horiz_pos(pos: str) -> str:
    p = (pos or "").lower()
    if "kiri" in p:
        return "kiri"
    if "kanan" in p:
        return "kanan"
    return "tengah"   # tengah / atas / bawah / depan → dianggap "tengah/depan"


# ─── Waktu ────────────────────────────────────────────────────────────────────

def now():
    """(epoch_float, iso_local, monotonic) — iso pakai format yang sama dgn device."""
    return (time.time(),
            time.strftime("%Y-%m-%dT%H:%M:%S"),
            time.monotonic())


# ─── Sesi & file ────────────────────────────────────────────────────────────────

def session_dir(session: str, create: bool = False) -> str:
    d = os.path.join(SESSION_ROOT, session)
    if create:
        os.makedirs(d, exist_ok=True)
    return d


def append_jsonl(path: str, obj: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    line = json.dumps(obj, ensure_ascii=False)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def read_jsonl(path: str) -> list:
    out = []
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                pass
    return out


# ─── HTTP (stdlib) ──────────────────────────────────────────────────────────────

def http_get(base: str, path: str, timeout: float = 4.0):
    """GET → (status_code, body_bytes). Tidak melempar pada HTTP error."""
    url = base.rstrip("/") + path
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        return 0, str(e).encode()


def http_get_json(base: str, path: str, timeout: float = 4.0):
    code, body = http_get(base, path, timeout)
    if code != 200:
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return None


def http_post_json(base: str, path: str, payload: dict,
                   token: str = "", timeout: float = 20.0):
    """POST JSON → (status_code, parsed_or_text). Sertakan X-Auth-Token bila ada."""
    url = base.rstrip("/") + path
    data = json.dumps(payload or {}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Auth-Token"] = token
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            try:
                return r.status, json.loads(body)
            except json.JSONDecodeError:
                return r.status, body.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, ""
    except Exception as e:
        return 0, str(e)


def fetch_token(base: str = DEFAULT_BASE, timeout: float = 4.0) -> str:
    """Ambil device token via GET /auth/token (hanya jalan dari loopback/LAN).
    Kosong kalau ditolak (mis. dijalankan dari luar LAN)."""
    j = http_get_json(base, "/auth/token", timeout)
    if isinstance(j, dict):
        return j.get("token", "") or ""
    return ""


# ─── Parsing caption nav (mirror audio_manager._queue_nav) ───────────────────────
# caption nav = "{objid} {frasa_posisi}{ ' dekat' kalau near}"
#   contoh: "orang di sebelah kanan dekat", "kursi di depan", "mobil di sebelah kiri"

def parse_caption(text: str) -> dict:
    """Pecah caption nav jadi {label, pos, tier}. Mengembalikan label=None kalau
    caption bukan alert objek (mis. deskripsi scene / cue sistem)."""
    t = (text or "").lower()
    label = None
    for objid, lbl in ID_LABEL.items():
        # token-match sederhana (objid pendek & unik dalam kalimat nav)
        if objid in t.split() or (" " + objid + " ") in (" " + t + " "):
            label = lbl
            break
    pos = horiz_pos(t)
    tier = "near" if "dekat" in t else "far"
    return {"label": label, "pos": pos, "tier": tier}


def compact_det(d: dict) -> dict:
    """Status det → bentuk ringkas untuk events.jsonl."""
    lbl = d.get("label", "")
    return {
        "label": lbl,
        "id":    LABEL_ID.get(lbl, lbl),
        "conf":  d.get("confidence"),
        "pos":   d.get("position", ""),
        "tier":  d.get("tier", "far"),
        "danger": bool(d.get("is_danger")),
        "area":  d.get("area_ratio"),
    }


def pct(values, p):
    """Persentil sederhana (nearest-rank). values: list angka. p: 0..1."""
    xs = sorted(v for v in values if v is not None)
    if not xs:
        return None
    idx = min(len(xs) - 1, int(round(p * (len(xs) - 1))))
    return xs[idx]


def mean(values):
    xs = [v for v in values if v is not None]
    return (sum(xs) / len(xs)) if xs else None

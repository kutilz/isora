"""
AuralAI — Per-device identity (multi-device safe).

Single source of truth for how a unit names and announces itself so that 5
devices on the same LAN never collide. Each unit derives a unique short id from
its own WiFi MAC; the friendly name and `.local` hostname follow from that.

Public API (all pure-python, never raises):
  device_id(short)      → stable hex id, e.g. "bfe2"
  default_device_name() → "aural-<id>"
  device_name()         → configured name if set & valid, else the default
  sanitize_name(s)      → DNS-label-safe form of a user-supplied name
  mdns_hostname()       → "<device_name>.local"
  current_ip()          → best-effort current LAN IPv4 ("" if offline)
  onboarding_phrase()   → one Indonesian-TTS sentence telling a helper how to connect
"""

import re
import socket
import uuid
from typing import Optional

# The device is reached over WiFi, so wlan0's MAC is the identity the user knows
# the box by (it is also what was printed on the label). Fall back to wired.
_MAC_IFACES = ("wlan0", "eth0", "usb0")


def _read_iface_mac(iface: str) -> str:
    try:
        with open(f"/sys/class/net/{iface}/address") as f:
            return f.read().strip().lower()
    except Exception:
        return ""


def _mac_hex() -> str:
    """12 hex digits (no separators) of the best available MAC, or ""."""
    for iface in _MAC_IFACES:
        mac = _read_iface_mac(iface)
        if mac and mac != "00:00:00:00:00:00":
            return mac.replace(":", "")
    # uuid.getnode(): trust only if it returned a real (not fabricated) MAC.
    try:
        node = uuid.getnode()
        if not (node >> 40) & 1:          # bit set ⇒ randomised/fabricated
            return f"{node:012x}"
    except Exception:
        pass
    # Last resort: a stable-ish suffix from machine-id (keeps the name constant).
    for p in ("/etc/machine-id", "/proc/sys/kernel/random/boot_id"):
        try:
            with open(p) as f:
                s = f.read().strip().replace("-", "")
                if s:
                    return s[-12:]
        except Exception:
            pass
    return ""


def device_id(short: bool = True) -> str:
    """Stable lowercase hex id. short=True → last 4 hex (2 MAC bytes), e.g. 'bfe2'."""
    h = _mac_hex()
    if not h:
        return "device"
    return h[-4:] if short else h[-6:]


def default_device_name() -> str:
    return f"aural-{device_id(short=True)}"


def sanitize_name(name: str) -> str:
    """DNS-label-safe: lowercase, [a-z0-9-] only, collapse, trim, max 30 chars."""
    s = (name or "").strip().lower()
    s = re.sub(r"[^a-z0-9-]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s[:30]


def device_name() -> str:
    """Configured name if set & valid, else the MAC-derived default."""
    raw = ""
    try:
        from config import cfg
        raw = cfg.get("device_name", "") or ""
    except Exception:
        pass
    return sanitize_name(raw) or default_device_name()


def mdns_hostname() -> str:
    return f"{device_name()}.local"


def current_ip() -> str:
    """Best-effort current LAN IPv4 ('' if offline)."""
    # 1. MaixPy WiFi API (matches wifi_connect.py / aural_maix.py usage).
    try:
        from maix import network
        ip = (network.wifi.Wifi().get_ip() or "").strip()
        if ip and not ip.startswith("0."):
            return ip
    except Exception:
        pass
    # 2. Outbound-socket trick — fills in even when get_ip() is empty.
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return ""
    finally:
        if s is not None:
            try:
                s.close()
            except Exception:
                pass


# ─── Indonesian TTS phrasing (no screen → must be intelligible by ear) ────────

# Hex ids only contain 0-9 a-f; map those to clear Indonesian syllables.
_SPELL_ID = {
    "a": "a", "b": "be", "c": "ce", "d": "de", "e": "e", "f": "ef",
    "0": "nol", "1": "satu", "2": "dua", "3": "tiga", "4": "empat",
    "5": "lima", "6": "enam", "7": "tujuh", "8": "delapan", "9": "sembilan",
}


def _spell(token: str) -> str:
    """Spell a short token (e.g. the hex id) syllable-by-syllable."""
    return " ".join(_SPELL_ID.get(ch, ch) for ch in token.lower())


def _spell_ip(ip: str) -> str:
    """'10.146.235.103' → digit-by-digit with spoken 'titik' separators."""
    out = []
    for i, part in enumerate(ip.split(".")):
        if i:
            out.append("titik")
        out.append(" ".join(_SPELL_ID.get(d, d) for d in part))
    return " ".join(out)


def _spoken_host(base_url: str) -> str:
    """'https://auralai.app' → 'auralai titik app' (intelligible by ear)."""
    host = (base_url or "").split("//")[-1].split("/")[0]
    host = host.split(":")[0]  # drop port
    return host.replace(".", " titik ").replace("-", " strip ")


def pairing_phrase(code: str, base_url: str = "https://auralai.app") -> str:
    """
    Spoken sentence telling a helper how to pair via the web hub using a code.
    Returned as a single string so it caches as exactly one TTS wav.
    """
    site = _spoken_host(base_url) or "auralai titik app"
    spelled = _spell(code)
    return " ".join([
        "AuralAI siap.",
        f"Untuk menghubungkan, buka {site} di ponsel,",
        f"lalu masukkan kode: {spelled}.",
        "Tekan tombol sebentar untuk mengulang kode, atau tekan agak lama bila sudah selesai.",
    ])


def onboarding_phrase(port: int = 8080) -> str:
    """
    One spoken sentence telling a helper how to open the dashboard. Returned as a
    single string so it caches as exactly one TTS wav.
    """
    name = device_name()
    ip = current_ip()
    host_spoken = name.replace("-", " strip ")
    parts = [
        "AuralAI siap digunakan.",
        "Untuk membuka panel kontrol, sambungkan ponsel ke jaringan WiFi yang sama,",
    ]
    if ip:
        parts.append(f"lalu buka alamat: {_spell_ip(ip)}, port {port}.")
        parts.append(f"Atau ketik nama: {host_spoken} titik lokal.")
    else:
        parts.append(f"lalu ketik alamat: {host_spoken} titik lokal, port {port}.")
    parts.append(f"Bagian belakang nama dieja: {_spell(device_id())}.")
    parts.append("Tekan tombol sebentar untuk mengulang, atau tekan agak lama bila sudah paham.")
    return " ".join(parts)

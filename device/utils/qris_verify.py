"""
QRIS local decoder + verifier.

Tries multiple zbar bindings (pyzbar > pillow+zbar > opencv fallback);
all imports are guarded so the module never blocks startup when none
of them are installed on MaixCAM.

Parses the standard EMVCo QRIS payload (TLV format) for:
  - merchant_name (tag 59)
  - merchant_city (tag 60)
  - nominal       (tag 54 inside template 54)
  - currency      (tag 53)

`verify_qris(jpeg_bytes, ai_text)` returns a dict suitable for the
hybrid flow:
    {
        "decoded":   True/False,
        "merchant":  "...", "city": "...", "nominal": 12500, "currency": "360",
        "ai_text":   "<raw ai output>",
        "ai_match":  True/False,   # AI nominal matches local nominal
        "warning":   "..."         # e.g. "Nominal AI berbeda dari QR — abaikan AI"
    }
"""

from typing import Optional, Tuple


# ─── Lazy decoder selection ───────────────────────────────────────────────────

def _try_pyzbar():
    try:
        from pyzbar import pyzbar
        from PIL import Image
        import io
        def decode(jpeg_bytes: bytes) -> Optional[str]:
            img = Image.open(io.BytesIO(jpeg_bytes))
            results = pyzbar.decode(img)
            for r in results:
                if r.data:
                    return r.data.decode("utf-8", errors="replace")
            return None
        return decode
    except Exception:
        return None


def _try_opencv():
    try:
        import cv2
        import numpy as np
        det = cv2.QRCodeDetector()
        def decode(jpeg_bytes: bytes) -> Optional[str]:
            arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
            if img is None:
                return None
            data, _pts, _ = det.detectAndDecode(img)
            return data or None
        return decode
    except Exception:
        return None


_decoder = None
_decoder_name = "none"


def _get_decoder():
    global _decoder, _decoder_name
    if _decoder is not None or _decoder_name != "none":
        return _decoder
    for name, factory in (("pyzbar", _try_pyzbar), ("opencv", _try_opencv)):
        d = factory()
        if d is not None:
            _decoder, _decoder_name = d, name
            return d
    _decoder_name = "unavailable"
    return None


def decoder_name() -> str:
    """Report which decoder is in use (for /health and logs)."""
    _get_decoder()
    return _decoder_name


# ─── EMVCo TLV parser ─────────────────────────────────────────────────────────

def _parse_tlv(s: str) -> dict:
    """Parse a flat EMVCo-style TLV string into {id: value}."""
    out = {}
    i = 0
    while i + 4 <= len(s):
        tag = s[i:i+2]
        try:
            ln = int(s[i+2:i+4])
        except ValueError:
            break
        val = s[i+4 : i+4+ln]
        if len(val) < ln:
            break
        out[tag] = val
        i += 4 + ln
    return out


def parse_qris_payload(payload: str) -> dict:
    """Return parsed merchant/nominal/etc. Empty fields on parse failure."""
    if not payload:
        return {}
    tlv = _parse_tlv(payload)
    info = {
        "raw":           payload,
        "merchant_name": tlv.get("59", "").strip(),
        "merchant_city": tlv.get("60", "").strip(),
        "currency":      tlv.get("53", ""),
        "country":       tlv.get("58", ""),
        "postal_code":   tlv.get("61", ""),
    }
    # Nominal — tag 54 (transaction amount, optional)
    nom = tlv.get("54", "").strip()
    if nom:
        try:
            info["nominal"] = float(nom)
        except ValueError:
            info["nominal"] = None
    else:
        info["nominal"] = None
    return info


# ─── Public API ───────────────────────────────────────────────────────────────

def decode_qris(jpeg_bytes: bytes) -> dict:
    """Decode QRIS from JPEG. Returns {} if no decoder or no code found."""
    d = _get_decoder()
    if d is None or not jpeg_bytes:
        return {}
    try:
        payload = d(jpeg_bytes)
    except Exception:
        return {}
    if not payload:
        return {}
    return parse_qris_payload(payload)


def _extract_ai_nominal(ai_text: str) -> Optional[float]:
    """Pull a NOMINAL: <digits> value from the AI-formatted response."""
    if not ai_text:
        return None
    import re
    m = re.search(r"NOMINAL\s*[:=]\s*([0-9.,]+)", ai_text, flags=re.IGNORECASE)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "").replace(".", ""))
    except ValueError:
        return None


def verify_against_ai(local: dict, ai_text: str) -> dict:
    """Compare local-decoded payload against AI-reported nominal."""
    if not local:
        return {
            "decoded": False,
            "ai_text": ai_text,
            "ai_match": False,
            "warning": "QRIS tidak terbaca oleh decoder lokal.",
        }
    ai_nom = _extract_ai_nominal(ai_text)
    local_nom = local.get("nominal")
    match = (ai_nom is not None and local_nom is not None
             and abs(ai_nom - local_nom) < 1.0)
    warn = ""
    if ai_nom is not None and local_nom is not None and not match:
        warn = (f"Nominal berbeda: AI={ai_nom:.0f}, QR={local_nom:.0f} "
                f"— gunakan nilai QR.")
    elif local_nom is None and ai_nom is not None:
        warn = ("QR tidak menyertakan nominal — gunakan input manual saat "
                "transaksi.")
    return {
        "decoded":       True,
        "ai_text":       ai_text,
        "ai_nominal":    ai_nom,
        "local_nominal": local_nom,
        "merchant":      local.get("merchant_name", ""),
        "city":          local.get("merchant_city", ""),
        "currency":      local.get("currency", ""),
        "ai_match":      match,
        "warning":       warn,
    }


def format_audio_message(verified: dict, cap: int = 1_000_000) -> Tuple[str, bool]:
    """
    Build a Bahasa Indonesia audio message from verified QRIS data.
    Returns (text, is_safe_to_transact). When unsafe, the message is
    a clear "tidak terbaca" so the user retries instead of paying wrong.

    `cap` = nominal threshold (IDR) above which we warn.
    """
    if not verified.get("decoded"):
        return ("QRIS tidak terbaca dengan jelas. Mohon ulangi pemindaian.", False)

    merchant = verified.get("merchant") or "merchant tidak diketahui"
    nominal  = verified.get("local_nominal")
    warning  = verified.get("warning", "")

    parts = [f"Merchant {merchant}"]
    if nominal is not None:
        parts.append(f"nominal {int(nominal):,} rupiah".replace(",", "."))
        if nominal > cap:
            parts.append(
                f"melebihi batas {int(cap):,} rupiah — mohon konfirmasi dua kali."
                .replace(",", ".")
            )
    else:
        parts.append("nominal tidak tertera di QR")

    if warning and not verified.get("ai_match", False):
        parts.append(warning)

    return ", ".join(parts) + ".", True

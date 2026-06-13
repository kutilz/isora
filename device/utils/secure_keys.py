"""
Symmetric encryption for API keys at rest.

Design goals (per user requirement, prioritising sustainability):
  - Hardcoded API keys can be set at deploy time and stored encrypted
    in /root/config.json under "*_api_key_enc" fields.
  - Decryption uses a device-derived key (machine-id + salt) so that
    pulling the SD card and reading config.json alone is not enough.
  - NO key rotation lockout — if the device key changes (re-flash),
    operator can re-run tools/set_api_key.py to re-encrypt.
  - Fallback chain when reading a key:
        1. AURAL_*_API_KEY env var (dev override)
        2. plaintext config key (legacy)
        3. encrypted config key, decrypted with device key
     → never bricks: if decryption fails, function returns "" and
       the adapter surfaces a clear AdapterError.

Crypto: AES-256-GCM via the `cryptography` library if available;
falls back to a hand-rolled HMAC-SHA256 stream cipher (XOR with
HKDF-expanded keystream) when cryptography is not installed on the
MaixCAM. Both are authenticated.

Storage format (base64 in JSON):
    "<version>.<nonce_b64>.<ciphertext_b64>.<tag_b64>"
    version: "v1"  (AES-GCM)
              "v2"  (HKDF-stream + HMAC, fallback)
"""

import base64
import hashlib
import hmac
import os
import secrets
from typing import Optional

# ─── Device key derivation ────────────────────────────────────────────────────

_SALT       = b"AuralAI-SDK::secure_keys::v1"
_MACHINE_ID_PATHS = (
    "/etc/machine-id",
    "/var/lib/dbus/machine-id",
    "/proc/sys/kernel/random/boot_id",
)


def _machine_seed() -> bytes:
    """Stable seed across boots — falls back to MAC if no machine-id."""
    for p in _MACHINE_ID_PATHS:
        try:
            with open(p, "rb") as f:
                data = f.read().strip()
                if data:
                    return data
        except Exception:
            pass
    # Fallback: hostname + MAC of first interface (less stable but works)
    try:
        import uuid
        return f"{uuid.getnode():012x}".encode()
    except Exception:
        return b"unknown-device"


def _device_key() -> bytes:
    """Derive a 32-byte symmetric key from machine-id + static salt."""
    seed = _machine_seed()
    return hashlib.sha256(_SALT + seed).digest()


# ─── HKDF stream cipher fallback (no external deps) ───────────────────────────

def _hkdf_expand(key: bytes, info: bytes, length: int) -> bytes:
    """RFC 5869 HKDF-Expand, SHA-256."""
    out = b""
    counter = 1
    block = b""
    while len(out) < length:
        block = hmac.new(key, block + info + bytes([counter]), hashlib.sha256).digest()
        out += block
        counter += 1
    return out[:length]


def _enc_v2(plaintext: bytes, key: bytes) -> str:
    nonce  = secrets.token_bytes(16)
    stream = _hkdf_expand(key, b"stream:" + nonce, len(plaintext))
    ct     = bytes(p ^ s for p, s in zip(plaintext, stream))
    tag    = hmac.new(key, b"mac:" + nonce + ct, hashlib.sha256).digest()[:16]
    return ".".join([
        "v2",
        base64.b64encode(nonce).decode(),
        base64.b64encode(ct).decode(),
        base64.b64encode(tag).decode(),
    ])


def _dec_v2(parts, key: bytes) -> Optional[bytes]:
    try:
        nonce = base64.b64decode(parts[1])
        ct    = base64.b64decode(parts[2])
        tag   = base64.b64decode(parts[3])
    except Exception:
        return None
    expected = hmac.new(key, b"mac:" + nonce + ct, hashlib.sha256).digest()[:16]
    if not hmac.compare_digest(expected, tag):
        return None
    stream = _hkdf_expand(key, b"stream:" + nonce, len(ct))
    return bytes(c ^ s for c, s in zip(ct, stream))


# ─── AES-GCM (preferred) ──────────────────────────────────────────────────────

def _try_aes_gcm():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        return AESGCM
    except Exception:
        return None


def _enc_v1(plaintext: bytes, key: bytes) -> Optional[str]:
    AESGCM = _try_aes_gcm()
    if AESGCM is None:
        return None
    nonce = secrets.token_bytes(12)
    ct    = AESGCM(key).encrypt(nonce, plaintext, None)
    # AESGCM concatenates ct||tag; split last 16 bytes as tag for portability
    body, tag = ct[:-16], ct[-16:]
    return ".".join([
        "v1",
        base64.b64encode(nonce).decode(),
        base64.b64encode(body).decode(),
        base64.b64encode(tag).decode(),
    ])


def _dec_v1(parts, key: bytes) -> Optional[bytes]:
    AESGCM = _try_aes_gcm()
    if AESGCM is None:
        return None
    try:
        nonce = base64.b64decode(parts[1])
        body  = base64.b64decode(parts[2])
        tag   = base64.b64decode(parts[3])
        return AESGCM(key).decrypt(nonce, body + tag, None)
    except Exception:
        return None


# ─── Public API ───────────────────────────────────────────────────────────────

def encrypt(plaintext: str) -> str:
    """Encrypt a plaintext key. Returns the storage string (v1 if AES-GCM
    available, else v2 fallback)."""
    if not plaintext:
        return ""
    key = _device_key()
    data = plaintext.encode("utf-8")
    enc = _enc_v1(data, key)
    if enc is not None:
        return enc
    return _enc_v2(data, key)


def decrypt(stored: str) -> str:
    """Decrypt a stored ciphertext. Returns "" if format unknown or
    auth fails — never raises. Empty input → empty output."""
    if not stored:
        return ""
    parts = stored.split(".")
    if len(parts) != 4:
        return ""
    key = _device_key()
    if parts[0] == "v1":
        out = _dec_v1(parts, key)
    elif parts[0] == "v2":
        out = _dec_v2(parts, key)
    else:
        return ""
    if out is None:
        return ""
    try:
        return out.decode("utf-8")
    except Exception:
        return ""


def is_ciphertext(value: str) -> bool:
    """Heuristic: does this look like our encrypted format?"""
    if not value:
        return False
    parts = value.split(".")
    return len(parts) == 4 and parts[0] in ("v1", "v2")


# Convenience: read+decrypt a config key with full fallback chain
def read_secret(cfg_obj, base_key: str, env_var: str) -> str:
    """
    Resolve a secret with priority:
        env var > plaintext config > encrypted config (decrypted)
    Returns "" if nothing usable found.
    """
    env_val = os.environ.get(env_var, "")
    if env_val:
        return env_val
    plain = cfg_obj.get(base_key, "") or ""
    if plain and not is_ciphertext(plain):
        return plain
    enc_field = f"{base_key}_enc"
    enc_val = cfg_obj.get(enc_field, "") or ""
    if enc_val:
        return decrypt(enc_val)
    # last resort: if base_key happened to be a ciphertext (legacy upgrade)
    if plain and is_ciphertext(plain):
        return decrypt(plain)
    return ""

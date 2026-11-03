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
        1. ISORA_*_API_KEY env var (dev override)
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
# Self-generated, self-persisted seed rather than the platform machine-id:
# on this device's image, /etc/machine-id is absent and dbus-uuidgen
# regenerates /var/lib/dbus/machine-id on every boot instead of reusing an
# existing one, so anything encrypted under the old machine-id-derived key
# silently failed to decrypt after the next reboot (confirmed 2026-07-12 —
# a key that decrypted fine pre-reboot returned "" post-reboot). Generating
# our own seed once and persisting it ourselves removes that dependency; it
# lives on the same SD-card partition as config.json either way, so this
# isn't a security regression versus the old scheme.
_SEED_FILE = "/root/.isora_secure_seed"
_MIN_SEED_LEN = 16
# Where the AuralAI firmware kept the same seed. A unit moved from AuralAI to
# I-Sora must ADOPT it rather than mint a new one: every *_api_key_enc in the
# config.json it keeps — and the E2E private key the paired phone encrypts
# to — is sealed under it, so a fresh seed silently loses all of them
# (seen 2026-10-21 on aural-88dd: "E2E keypair unusable ... regenerating").
_LEGACY_SEED_FILES = ("/root/.aural_secure_seed",)

# Last-resort seed when _SEED_FILE cannot be persisted at all (read-only /root
# after an fsck, ENOSPC, or running non-root). It MUST stay stable within the
# process: _device_key() is called separately by encrypt and decrypt, so a value
# that changes between calls means a key encrypted a moment ago decrypts to ""
# and every adapter reports "api_key not configured", silently and permanently.
_fallback_seed = None


def _read_seed(path: str = None) -> bytes:
    """Return the persisted seed, or b"" if it is absent/short/unreadable."""
    try:
        with open(path or _SEED_FILE, "rb") as f:
            data = f.read()
    except Exception:
        return b""
    return data if len(data) >= _MIN_SEED_LEN else b""


def _legacy_seed() -> bytes:
    for path in _LEGACY_SEED_FILES:
        data = _read_seed(path)
        if data:
            return data
    return b""


def _stable_fallback_seed() -> bytes:
    """Machine-derived seed for when the file cannot be written.

    Not stable across a re-flash, but stable across calls and reboots, which is
    what matters: a value that changes between the encrypt and the decrypt of
    the same key makes every adapter report "api_key not configured", silently
    and permanently.

    Every source below survives a power cycle. Two that look like obvious
    candidates are deliberately absent: /var/lib/dbus/machine-id (dbus-uuidgen
    regenerates it on EVERY boot on this image — see the header; seeding from it
    reintroduces the exact lost-after-reboot bug _SEED_FILE was written to fix)
    and /proc/sys/kernel/random/boot_id (per-boot by definition).
    """
    global _fallback_seed
    if _fallback_seed is not None:
        return _fallback_seed
    # /etc/machine-id: absent on this image, stable where it exists (a normal
    # distro writes it once at first boot). mmcblk*/device/cid: the SD card's
    # factory CID register — unique per card and untouched by a re-flash.
    for p in ("/etc/machine-id",
              "/sys/block/mmcblk0/device/cid",
              "/sys/block/mmcblk1/device/cid"):
        try:
            with open(p, "rb") as f:
                data = f.read().strip()
            if len(data) >= _MIN_SEED_LEN:
                _fallback_seed = data
                return _fallback_seed
        except Exception:
            pass
    # The WiFi MAC, read the same way identity.py reads it — including its
    # check that uuid.getnode() returned a REAL MAC and not the fabricated
    # random node it invents when it cannot find one (which would be a fresh
    # value every process). Prefixed because 12 hex digits alone is under
    # _MIN_SEED_LEN.
    try:
        from utils.identity import _mac_hex
        mac = _mac_hex()
        if mac:
            _fallback_seed = ("isora-mac-" + mac).encode()
            return _fallback_seed
    except Exception:
        pass
    # Nothing stable left. Random keeps this process self-consistent; keys
    # written under it simply will not survive a restart.
    _fallback_seed = secrets.token_bytes(32)
    return _fallback_seed


def _machine_seed() -> bytes:
    """Stable seed across boots — generated once, persisted at _SEED_FILE."""
    existing = _read_seed()
    if existing:
        return existing

    seed = _legacy_seed() or secrets.token_bytes(32)
    try:
        fd = os.open(_SEED_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(seed)
            f.flush()
            # Without this, a power cut right after create leaves a 0-byte seed
            # file that exists but is useless — and O_EXCL then fails forever.
            os.fsync(f.fileno())
        return seed
    except FileExistsError:
        # Either another process won the race, or a previous run died between
        # the create and the write. Re-read through the SAME length check —
        # returning the raw contents here would hand back b"" for a truncated
        # file, making _device_key() the identical constant sha256(_SALT + b"")
        # on every device that hits it.
        existing = _read_seed()
        if existing:
            return existing
        # The file is present but unusable. It can never yield a valid key, so
        # replace it atomically rather than deriving from nothing.
        try:
            tmp = _SEED_FILE + ".tmp"
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(seed)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, _SEED_FILE)
            return seed
        except Exception:
            return _stable_fallback_seed()
    except Exception:
        # Could not create the file at all — do NOT return fresh randomness,
        # which would differ between the encrypt and decrypt of the same key.
        return _stable_fallback_seed()


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

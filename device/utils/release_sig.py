"""
ECDSA P-256 / SHA-256 signatures for device releases — pure Python.

The updater (core/updater.py) installs code that then runs as root, so a
release is only accepted if it is signed by the team's release key. HTTPS
alone is not enough: it proves the bytes came from GitHub, not that the person
who published them should be trusted, and the repo is public.

Reuses the P-256 arithmetic already in utils/crypto_box.py (the MaixCAM cannot
build `cryptography`). Verification is two scalar multiplications — a fraction
of a second on the device, once per update check. Signing only ever runs on a
laptop (tools/release.py).

Wire format: a signature is r || s, 32 bytes each, big-endian (64 bytes), the
same "raw" form WebCrypto produces. The public key is the 65-byte uncompressed
point, base64.
"""

import base64
import hashlib
import secrets

from utils.crypto_box import _GX, _GY, _N, _P, _jac_add, _raw_to_pub, _scalar_mult

# y^2 = x^3 - 3x + b  (P-256)
_B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B


def release_message(version: str, sha256_hex: str, size: int) -> bytes:
    """Exactly what a release signature covers. The tarball itself is bound
    through its hash; the download URL is deliberately not, so a release can
    move hosts without re-signing."""
    return ("isora-device-release/1\n%s\n%s\n%d\n" % (version, sha256_hex, size)).encode()


def _digest(msg: bytes) -> int:
    return int.from_bytes(hashlib.sha256(msg).digest(), "big")


def _on_curve(x: int, y: int) -> bool:
    return 0 <= x < _P and 0 <= y < _P and (y * y - (x * x * x - 3 * x + _B)) % _P == 0


def public_key(b64: str):
    """Decode + validate a base64 uncompressed point. Raises ValueError."""
    Q = _raw_to_pub(base64.b64decode(b64))
    if not _on_curve(*Q):
        raise ValueError("public key is not on P-256")
    return Q


def verify(pub_b64: str, msg: bytes, sig: bytes) -> bool:
    """True only for a valid signature of `msg` under `pub_b64`. Never raises."""
    try:
        Q = public_key(pub_b64)
        if len(sig) != 64:
            return False
        r = int.from_bytes(sig[:32], "big")
        s = int.from_bytes(sig[32:], "big")
        if not (1 <= r < _N and 1 <= s < _N):
            return False
        w = pow(s, -1, _N)
        e = _digest(msg)
        u1 = (e * w) % _N
        u2 = (r * w) % _N
        p1 = _scalar_mult(u1, _GX, _GY) if u1 else None
        p2 = _scalar_mult(u2, Q[0], Q[1])
        if p1 is None and p2 is None:
            return False
        if p1 is None:
            x = p2[0]
        elif p2 is None:
            x = p1[0]
        else:
            X, Y, Z = _jac_add(p1[0], p1[1], 1, p2[0], p2[1], 1)
            if Z == 0:
                return False
            zi = pow(Z, _P - 2, _P)
            x = (X * zi * zi) % _P
        return x % _N == r
    except Exception:
        return False


def generate_keypair() -> tuple:
    """(private scalar as hex, public key as base64). Laptop-side only."""
    d = secrets.randbelow(_N - 1) + 1
    x, y = _scalar_mult(d, _GX, _GY)
    pub = b"\x04" + x.to_bytes(32, "big") + y.to_bytes(32, "big")
    return "%064x" % d, base64.b64encode(pub).decode()


def sign(priv_hex: str, msg: bytes) -> bytes:
    """r || s for `msg`. Laptop-side only (tools/release.py)."""
    d = int(priv_hex, 16)
    if not 1 <= d < _N:
        raise ValueError("bad private key")
    e = _digest(msg)
    while True:
        k = secrets.randbelow(_N - 1) + 1
        R = _scalar_mult(k, _GX, _GY)
        r = R[0] % _N
        if r == 0:
            continue
        s = (pow(k, -1, _N) * (e + r * d)) % _N
        if s == 0:
            continue
        return r.to_bytes(32, "big") + s.to_bytes(32, "big")

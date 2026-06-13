"""
End-to-end keypair for receiving encrypted secrets (API keys) from the web.

The web encrypts a secret to this device's PUBLIC key; only this device can
decrypt it, so the cloud relay never sees plaintext keys. Scheme matches
web/lib/e2e.ts and tools/mock_device.py:

    ecdh-p256-aesgcm (v1)
      ECDH(P-256) → HKDF-SHA256(salt="auralai-e2e-salt", info="auralai-e2e-v1")
      → AES-256-GCM

This implementation is **pure Python, zero native dependencies**, because the
MaixCAM (riscv64) cannot build/install `cryptography`. It is only used for a
handful of one-shot decryptions (config pushes), so performance is fine.

Persisted in config:
    device_pubkey       — raw uncompressed point (0x04||X||Y), base64
    device_privkey_enc  — private scalar (hex), encrypted at rest via secure_keys

Public API (unchanged): available(), ensure_keypair(cfg), public_key_b64(cfg),
unseal(cfg, sealed).
"""

import base64
import hashlib
import hmac
import secrets as _secrets

E2E_SALT = b"auralai-e2e-salt"
E2E_INFO = b"auralai-e2e-v1"


# ══════════════════════════════════════════════════════════════════════════════
# P-256 (secp256r1) — Jacobian coordinates (one modular inverse per operation set)
# ══════════════════════════════════════════════════════════════════════════════

_P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
_A = _P - 3
_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
_GX = 0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296
_GY = 0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5


def _jac_double(X1, Y1, Z1):
    if Y1 == 0:
        return (0, 0, 0)
    A = (Y1 * Y1) % _P
    B = (4 * X1 * A) % _P
    C = (8 * A * A) % _P
    D = (3 * (X1 - Z1 * Z1) * (X1 + Z1 * Z1)) % _P  # uses a = -3
    X3 = (D * D - 2 * B) % _P
    Y3 = (D * (B - X3) - C) % _P
    Z3 = (2 * Y1 * Z1) % _P
    return (X3, Y3, Z3)


def _jac_add(X1, Y1, Z1, X2, Y2, Z2):
    if Z1 == 0:
        return (X2, Y2, Z2)
    if Z2 == 0:
        return (X1, Y1, Z1)
    Z1Z1 = (Z1 * Z1) % _P
    Z2Z2 = (Z2 * Z2) % _P
    U1 = (X1 * Z2Z2) % _P
    U2 = (X2 * Z1Z1) % _P
    S1 = (Y1 * Z2 * Z2Z2) % _P
    S2 = (Y2 * Z1 * Z1Z1) % _P
    if U1 == U2:
        if S1 != S2:
            return (0, 0, 0)
        return _jac_double(X1, Y1, Z1)
    H = (U2 - U1) % _P
    R = (S2 - S1) % _P
    HH = (H * H) % _P
    HHH = (H * HH) % _P
    V = (U1 * HH) % _P
    X3 = (R * R - HHH - 2 * V) % _P
    Y3 = (R * (V - X3) - S1 * HHH) % _P
    Z3 = (H * Z1 * Z2) % _P
    return (X3, Y3, Z3)


def _scalar_mult(k, x, y):
    """k * (x,y) affine → affine (x,y). Returns None for the point at infinity."""
    rx, ry, rz = 0, 0, 0          # infinity
    ax, ay, az = x, y, 1
    while k:
        if k & 1:
            rx, ry, rz = _jac_add(rx, ry, rz, ax, ay, az)
        ax, ay, az = _jac_double(ax, ay, az)
        k >>= 1
    if rz == 0:
        return None
    zi = pow(rz, _P - 2, _P)
    zi2 = (zi * zi) % _P
    return ((rx * zi2) % _P, (ry * zi2 * zi) % _P)


def _gen_keypair():
    d = _secrets.randbelow(_N - 1) + 1
    Q = _scalar_mult(d, _GX, _GY)
    return d, Q


def _pub_to_raw(Q) -> bytes:
    x, y = Q
    return b"\x04" + x.to_bytes(32, "big") + y.to_bytes(32, "big")


def _raw_to_pub(b: bytes):
    if len(b) != 65 or b[0] != 4:
        raise ValueError("bad public point")
    return (int.from_bytes(b[1:33], "big"), int.from_bytes(b[33:65], "big"))


# ══════════════════════════════════════════════════════════════════════════════
# AES-256 (encrypt block only — GCM needs just the forward cipher) + GCM
# ══════════════════════════════════════════════════════════════════════════════

_SBOX = bytes.fromhex(
    "637c777bf26b6fc53001672bfed7ab76ca82c97dfa5947f0add4a2af9ca472c0"
    "b7fd9326363ff7cc34a5e5f171d8311504c723c31896059a071280e2eb27b275"
    "09832c1a1b6e5aa0523bd6b329e32f8453d100ed20fcb15b6acbbe394a4c58cf"
    "d0efaafb434d338545f9027f503c9fa851a3408f929d38f5bcb6da2110fff3d2"
    "cd0c13ec5f974417c4a77e3d645d197360814fdc222a908846eeb814de5e0bdb"
    "e0323a0a4906245cc2d3ac629195e479e7c8376d8dd54ea96c56f4ea657aae08"
    "ba78252e1ca6b4c6e8dd741f4bbd8b8a703eb5664803f60e613557b986c11d9e"
    "e1f8981169d98e949b1e87e9ce5528df8ca1890dbfe6426841992d0fb054bb16"
)


def _xtime(a):
    a <<= 1
    if a & 0x100:
        a ^= 0x11B
    return a & 0xFF


def _key_expansion(key: bytes):
    Nk, Nr = 8, 14
    w = [list(key[4 * i:4 * i + 4]) for i in range(Nk)]
    rcon = 1
    for i in range(Nk, 4 * (Nr + 1)):
        temp = list(w[i - 1])
        if i % Nk == 0:
            temp = temp[1:] + temp[:1]
            temp = [_SBOX[b] for b in temp]
            temp[0] ^= rcon
            rcon = _xtime(rcon)
        elif i % Nk == 4:
            temp = [_SBOX[b] for b in temp]
        w.append([w[i - Nk][j] ^ temp[j] for j in range(4)])
    # group into 15 round keys of 16 bytes
    return [bytes(b for word in w[4 * r:4 * r + 4] for b in word) for r in range(Nr + 1)]


def _aes_encrypt_block(round_keys, block: bytes) -> bytes:
    s = [list(block[i:i + 4]) for i in range(0, 16, 4)]  # rows? use column-major
    # state as 4x4 column-major: s[c][r]
    state = [[block[r + 4 * c] for r in range(4)] for c in range(4)]

    def add_rk(rk):
        for c in range(4):
            for r in range(4):
                state[c][r] ^= rk[r + 4 * c]

    add_rk(round_keys[0])
    for rnd in range(1, 14):
        # SubBytes
        for c in range(4):
            for r in range(4):
                state[c][r] = _SBOX[state[c][r]]
        # ShiftRows
        for r in range(1, 4):
            row = [state[c][r] for c in range(4)]
            row = row[r:] + row[:r]
            for c in range(4):
                state[c][r] = row[c]
        # MixColumns
        for c in range(4):
            a = state[c]
            t = a[0] ^ a[1] ^ a[2] ^ a[3]
            u = a[0]
            a[0] ^= t ^ _xtime(a[0] ^ a[1])
            a[1] ^= t ^ _xtime(a[1] ^ a[2])
            a[2] ^= t ^ _xtime(a[2] ^ a[3])
            a[3] ^= t ^ _xtime(a[3] ^ u)
        add_rk(round_keys[rnd])
    # final round (no MixColumns)
    for c in range(4):
        for r in range(4):
            state[c][r] = _SBOX[state[c][r]]
    for r in range(1, 4):
        row = [state[c][r] for c in range(4)]
        row = row[r:] + row[:r]
        for c in range(4):
            state[c][r] = row[c]
    add_rk(round_keys[14])
    return bytes(state[c][r] for c in range(4) for r in range(4))


def _gf_mult(x: bytes, y: bytes) -> bytes:
    R = 0xE1 << 120
    z = 0
    v = int.from_bytes(x, "big")
    yy = int.from_bytes(y, "big")
    for i in range(128):
        if (yy >> (127 - i)) & 1:
            z ^= v
        if v & 1:
            v = (v >> 1) ^ R
        else:
            v >>= 1
    return z.to_bytes(16, "big")


def _ghash(h: bytes, data: bytes) -> bytes:
    x = b"\x00" * 16
    for i in range(0, len(data), 16):
        block = data[i:i + 16]
        if len(block) < 16:
            block = block + b"\x00" * (16 - len(block))
        x = _gf_mult(bytes(a ^ b for a, b in zip(x, block)), h)
    return x


def _inc32(block: bytes) -> bytes:
    pre, ctr = block[:12], int.from_bytes(block[12:], "big")
    return pre + ((ctr + 1) & 0xFFFFFFFF).to_bytes(4, "big")


def _aes_gcm_decrypt(key: bytes, iv: bytes, ct_and_tag: bytes, aad: bytes = b"") -> bytes:
    rk = _key_expansion(key)
    h = _aes_encrypt_block(rk, b"\x00" * 16)
    if len(iv) == 12:
        j0 = iv + b"\x00\x00\x00\x01"
    else:
        s = _ghash(h, iv + b"\x00" * ((16 - len(iv) % 16) % 16) + b"\x00" * 8 + (len(iv) * 8).to_bytes(8, "big"))
        j0 = s
    tag = ct_and_tag[-16:]
    ct = ct_and_tag[:-16]

    # verify tag
    lens = (len(aad) * 8).to_bytes(8, "big") + (len(ct) * 8).to_bytes(8, "big")
    ghash_in = aad + b"\x00" * ((16 - len(aad) % 16) % 16) + ct + b"\x00" * ((16 - len(ct) % 16) % 16) + lens
    s = _ghash(h, ghash_in)
    expected = bytes(a ^ b for a, b in zip(s, _aes_encrypt_block(rk, j0)))
    if not hmac.compare_digest(expected, tag):
        raise ValueError("GCM tag mismatch")

    # CTR decrypt
    out = bytearray()
    ctr = _inc32(j0)
    for i in range(0, len(ct), 16):
        ks = _aes_encrypt_block(rk, ctr)
        block = ct[i:i + 16]
        out += bytes(a ^ b for a, b in zip(block, ks))
        ctr = _inc32(ctr)
    return bytes(out)


# ══════════════════════════════════════════════════════════════════════════════
# HKDF-SHA256
# ══════════════════════════════════════════════════════════════════════════════

def _hkdf(shared: bytes, salt: bytes, info: bytes, length: int = 32) -> bytes:
    prk = hmac.new(salt, shared, hashlib.sha256).digest()
    out, t, i = b"", b"", 1
    while len(out) < length:
        t = hmac.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
        out += t
        i += 1
    return out[:length]


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

def available() -> bool:
    return True   # pure Python — always available


def ensure_keypair(cfg) -> bool:
    if cfg.get("device_pubkey") and cfg.get("device_privkey_enc"):
        return True
    try:
        from utils.secure_keys import encrypt as enc_at_rest
    except Exception:
        enc_at_rest = lambda s: s  # noqa: E731
    d, Q = _gen_keypair()
    cfg.update({
        "device_pubkey": base64.b64encode(_pub_to_raw(Q)).decode(),
        "device_privkey_enc": enc_at_rest(format(d, "x")),
    })
    return True


def public_key_b64(cfg) -> str:
    return cfg.get("device_pubkey", "") or ""


def _load_scalar(cfg):
    enc = cfg.get("device_privkey_enc", "") or ""
    if not enc:
        return None
    try:
        from utils.secure_keys import decrypt as dec_at_rest, is_ciphertext
        hexd = dec_at_rest(enc) if is_ciphertext(enc) else enc
    except Exception:
        hexd = enc
    try:
        return int(hexd, 16)
    except Exception:
        return None


def unseal(cfg, sealed: dict) -> str:
    """Decrypt a sealed secret from web/lib/e2e.ts. Returns "" on any failure."""
    if not isinstance(sealed, dict) or sealed.get("alg") != "ecdh-p256-aesgcm":
        return ""
    d = _load_scalar(cfg)
    if d is None:
        return ""
    try:
        epk = _raw_to_pub(base64.b64decode(sealed["epk"]))
        shared_pt = _scalar_mult(d, epk[0], epk[1])
        if shared_pt is None:
            return ""
        shared = shared_pt[0].to_bytes(32, "big")
        key = _hkdf(shared, E2E_SALT, E2E_INFO, 32)
        pt = _aes_gcm_decrypt(
            key, base64.b64decode(sealed["iv"]), base64.b64decode(sealed["ct"])
        )
        return pt.decode("utf-8")
    except Exception:
        return ""

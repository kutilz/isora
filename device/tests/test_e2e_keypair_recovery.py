"""A device must never advertise a public key it can no longer decrypt for.

Observed on the real device (2026-09-11): `device_pubkey` and
`device_privkey_enc` were both present, so the old `ensure_keypair` returned
early — but the private half had been encrypted under an at-rest key that no
longer existed (the seed file is dated *after* it). Every API key the web
sealed to that public key failed to open: the relay was fine, the phone said
"terkirim", the device logged one line, and the assistant stayed mute forever.

The pair is therefore verified, not merely counted: the scalar must decrypt AND
re-derive the advertised public key.
"""

import base64

import pytest

from utils import crypto_box


class FakeCfg(dict):
    """Config stand-in: crypto_box only needs get() + update()."""


def _fresh():
    cfg = FakeCfg()
    crypto_box.ensure_keypair(cfg)
    return cfg


def test_a_new_device_gets_a_usable_pair():
    cfg = _fresh()
    assert crypto_box.keypair_status(cfg) == "ok"
    assert cfg["device_pubkey"] and cfg["device_privkey_enc"]


def test_an_existing_usable_pair_is_left_alone():
    """Boot must not churn the key — a new pubkey invalidates secrets in flight."""
    cfg = _fresh()
    before = cfg["device_pubkey"]
    crypto_box.ensure_keypair(cfg)
    assert cfg["device_pubkey"] == before


def test_missing_halves_report_missing():
    cfg = _fresh()
    pub, priv = cfg["device_pubkey"], cfg["device_privkey_enc"]

    cfg["device_privkey_enc"] = ""
    assert crypto_box.keypair_status(cfg) == "missing"

    cfg["device_privkey_enc"] = priv
    cfg["device_pubkey"] = ""
    assert crypto_box.keypair_status(cfg) == "missing"

    cfg["device_pubkey"] = pub
    assert crypto_box.keypair_status(cfg) == "ok"


def test_private_key_that_will_not_decrypt_is_regenerated():
    """The real failure: a well-formed ciphertext from a key that is gone."""
    cfg = _fresh()
    stale_pub = cfg["device_pubkey"]
    # Shaped like secure_keys' format (so is_ciphertext accepts it) but
    # undecryptable — exactly what a changed at-rest seed leaves behind.
    cfg["device_privkey_enc"] = "v1.AAAAAAAAAAAAAAAA.AAAAAAAA.AAAAAAAAAAAAAAAAAAAAAAAA"

    assert crypto_box.keypair_status(cfg) == "unusable"

    crypto_box.ensure_keypair(cfg)
    assert crypto_box.keypair_status(cfg) == "ok"
    assert cfg["device_pubkey"] != stale_pub


@pytest.mark.parametrize("garbage", ["", "not-hex", "0", "zz"])
def test_unparseable_private_key_is_unusable(garbage):
    cfg = _fresh()
    cfg["device_privkey_enc"] = garbage
    assert crypto_box.keypair_status(cfg) in ("missing", "unusable")


def test_mismatched_halves_are_unusable_even_though_both_decrypt():
    """Two valid halves of different pairs are as broken as one that won't open."""
    a, b = _fresh(), _fresh()
    assert a["device_pubkey"] != b["device_pubkey"]

    mixed = FakeCfg(device_pubkey=a["device_pubkey"], device_privkey_enc=b["device_privkey_enc"])
    assert crypto_box.keypair_status(mixed) == "unusable"

    crypto_box.ensure_keypair(mixed)
    assert crypto_box.keypair_status(mixed) == "ok"


def test_unseal_on_an_unusable_pair_returns_empty_not_an_exception():
    cfg = _fresh()
    cfg["device_privkey_enc"] = "v1.AAAAAAAAAAAAAAAA.AAAAAAAA.AAAAAAAAAAAAAAAAAAAAAAAA"
    sealed = {
        "alg": "ecdh-p256-aesgcm",
        "epk": base64.b64encode(b"\x04" + b"\x01" * 64).decode(),
        "iv": base64.b64encode(b"\x00" * 12).decode(),
        "ct": base64.b64encode(b"\x00" * 32).decode(),
    }
    assert crypto_box.unseal(cfg, sealed) == ""


# ─── invalid-curve points ────────────────────────────────────────────────────
# The point formulas never use the curve's b, so an off-curve ephemeral key is
# silently multiplied on a weaker curve. With an oracle for which decrypts
# succeed, a sender could recover the private scalar piece by piece.

def _seal(cfg, plaintext: bytes, epk_override=None) -> dict:
    """Seal like web/lib/e2e.ts, from crypto_box's own primitives."""
    import secrets
    pub = crypto_box._raw_to_pub(base64.b64decode(cfg["device_pubkey"]))
    e = secrets.randbelow(crypto_box._N - 1) + 1
    epk = crypto_box._scalar_mult(e, crypto_box._GX, crypto_box._GY)
    shared = crypto_box._scalar_mult(e, *pub)[0].to_bytes(32, "big")
    key = crypto_box._hkdf(shared, crypto_box.E2E_SALT, crypto_box.E2E_INFO, 32)
    iv = secrets.token_bytes(12)
    rk = crypto_box._key_expansion(key)
    h = crypto_box._aes_encrypt_block(rk, b"\x00" * 16)
    j0 = iv + b"\x00\x00\x00\x01"
    ct, ctr = bytearray(), crypto_box._inc32(j0)
    for i in range(0, len(plaintext), 16):
        ks = crypto_box._aes_encrypt_block(rk, ctr)
        ct += bytes(a ^ b for a, b in zip(plaintext[i:i + 16], ks))
        ctr = crypto_box._inc32(ctr)
    lens = (0).to_bytes(8, "big") + (len(ct) * 8).to_bytes(8, "big")
    s = crypto_box._ghash(h, bytes(ct) + b"\x00" * ((16 - len(ct) % 16) % 16) + lens)
    tag = bytes(a ^ b for a, b in zip(s, crypto_box._aes_encrypt_block(rk, j0)))
    raw_epk = epk_override or crypto_box._pub_to_raw(epk)
    return {"alg": "ecdh-p256-aesgcm", "epk": base64.b64encode(raw_epk).decode(),
            "iv": base64.b64encode(iv).decode(),
            "ct": base64.b64encode(bytes(ct) + tag).decode()}


def test_a_genuine_seal_still_opens():
    cfg = _fresh()
    assert crypto_box.unseal(cfg, _seal(cfg, b"sk-test-123")) == "sk-test-123"


def test_an_off_curve_ephemeral_key_is_refused_before_any_math():
    off = b"\x04" + (5).to_bytes(32, "big") + (7).to_bytes(32, "big")
    with pytest.raises(ValueError):
        crypto_box._raw_to_pub(off)
    cfg = _fresh()
    assert crypto_box.unseal(cfg, _seal(cfg, b"x", epk_override=off)) == ""


def test_coordinates_outside_the_field_are_refused():
    g = crypto_box._pub_to_raw((crypto_box._GX, crypto_box._GY))
    assert crypto_box._raw_to_pub(g) == (crypto_box._GX, crypto_box._GY)
    big = b"\x04" + (crypto_box._GX + crypto_box._P).to_bytes(33, "big")[-32:] + g[33:]
    with pytest.raises(ValueError):
        crypto_box._raw_to_pub(big)

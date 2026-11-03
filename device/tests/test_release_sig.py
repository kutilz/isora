"""Release signatures (utils/release_sig.py) — the only thing standing between
a public repo and root on every unit.

The ECDSA here is hand-written on top of crypto_box's P-256 (the device cannot
install `cryptography`), so it is checked against `cryptography` in BOTH
directions where that library is available on the dev machine.
"""

import base64
import json
import os

import pytest

from utils import release_sig

MSG = release_sig.release_message("2026.10.21.1", "ab" * 32, 123456)


@pytest.fixture(scope="module")
def keys():
    return release_sig.generate_keypair()


def test_sign_then_verify(keys):
    priv, pub = keys
    sig = release_sig.sign(priv, MSG)
    assert len(sig) == 64
    assert release_sig.verify(pub, MSG, sig)


@pytest.mark.parametrize("tamper", ["version", "hash", "size"])
def test_any_signed_field_change_breaks_the_signature(keys, tamper):
    priv, pub = keys
    sig = release_sig.sign(priv, MSG)
    fields = {"version": "2026.10.21.1", "hash": "ab" * 32, "size": 123456}
    fields[tamper] = {"version": "2026.10.21.2", "hash": "cd" * 32, "size": 123457}[tamper]
    other = release_sig.release_message(fields["version"], fields["hash"], fields["size"])
    assert not release_sig.verify(pub, other, sig)


def test_wrong_key_and_junk_are_rejected(keys):
    priv, pub = keys
    _, other_pub = release_sig.generate_keypair()
    sig = release_sig.sign(priv, MSG)
    assert not release_sig.verify(other_pub, MSG, sig)
    assert not release_sig.verify(pub, MSG, sig[:63])
    assert not release_sig.verify(pub, MSG, b"\x00" * 64)
    assert not release_sig.verify(pub, MSG, sig[:32] + b"\xff" * 32)
    assert not release_sig.verify("bm90IGEga2V5", MSG, sig)          # not a point
    bad_point = base64.b64encode(b"\x04" + b"\x01" * 64).decode()
    assert not release_sig.verify(bad_point, MSG, sig)


def test_compiled_public_key_is_a_valid_point():
    import ast
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "core" / "updater.py").read_text(
        encoding="utf-8")
    pub = next(n.value.value for n in ast.parse(src).body
               if isinstance(n, ast.Assign) and n.targets[0].id == "RELEASE_PUBKEY_B64")
    release_sig.public_key(pub)          # raises if malformed / off-curve


def test_compiled_key_matches_the_local_signing_key():
    """On the release laptop, the key in updater.py must be the one we sign with."""
    path = os.path.join(os.path.expanduser("~"), ".isora", "release-signing-key.json")
    if not os.path.exists(path):
        pytest.skip("no signing key on this machine")
    from core.updater import RELEASE_PUBKEY_B64
    with open(path) as f:
        key = json.load(f)
    assert key["pub"] == RELEASE_PUBKEY_B64
    assert release_sig.verify(key["pub"], MSG, release_sig.sign(key["d"], MSG))


# ─── cross-check against a reference implementation ─────────────────────────
# importorskip inside each test: at module level it would skip the whole file
# on a machine without `cryptography`, including the tests above.

def _ref():
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec, utils as ec_utils
    return hashes, serialization, ec, ec_utils


def test_reference_signature_verifies_here():
    hashes, serialization, ec, ec_utils = _ref()
    sk = ec.generate_private_key(ec.SECP256R1())
    r, s = ec_utils.decode_dss_signature(sk.sign(MSG, ec.ECDSA(hashes.SHA256())))
    raw = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    pub = sk.public_key().public_bytes(serialization.Encoding.X962,
                                       serialization.PublicFormat.UncompressedPoint)
    assert release_sig.verify(base64.b64encode(pub).decode(), MSG, raw)


def test_our_signature_verifies_in_the_reference(keys):
    hashes, serialization, ec, ec_utils = _ref()
    priv, pub = keys
    sig = release_sig.sign(priv, MSG)
    der = ec_utils.encode_dss_signature(int.from_bytes(sig[:32], "big"),
                                        int.from_bytes(sig[32:], "big"))
    pk = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), base64.b64decode(pub))
    pk.verify(der, MSG, ec.ECDSA(hashes.SHA256()))       # raises on failure

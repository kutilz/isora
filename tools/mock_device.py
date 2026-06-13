#!/usr/bin/env python3
"""
Mock AuralAI device — exercises the cloud relay end-to-end without hardware.

It mirrors what device/core/cloud.py will do:
  1. register (uploads a P-256 public key for E2E secrets)
  2. request a pairing code and PRINT IT BIG (type it into the web /pair page)
  3. long-poll for config commands, DECRYPT secrets, print the applied config, ACK
  4. send periodic heartbeats

State (device_id, secret, private key) is cached in tools/.mock_device.json so
re-runs keep the same identity.

Usage:
    python tools/mock_device.py --base-url http://localhost:3000
    python tools/mock_device.py --base-url https://your-app.vercel.app --reset

Requires: cryptography  (pip install cryptography)
"""

import argparse
import base64
import json
import os
import secrets as pysecrets
import sys
import time
import urllib.error
import urllib.request

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes, serialization

STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".mock_device.json")

# Must match web/lib/e2e.ts
E2E_SALT = b"auralai-e2e-salt"
E2E_INFO = b"auralai-e2e-v1"


# ─── state / identity ─────────────────────────────────────────────────────────

def load_state(reset: bool) -> dict:
    if reset and os.path.exists(STATE_PATH):
        os.remove(STATE_PATH)
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH) as f:
            return json.load(f)
    priv = ec.generate_private_key(ec.SECP256R1())
    priv_pem = priv.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    state = {
        "device_id": pysecrets.token_hex(8),       # 16 hex chars
        "secret": pysecrets.token_hex(32),         # device secret
        "priv_pem": priv_pem,
    }
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)
    return state


def pubkey_b64(priv) -> str:
    raw = priv.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    return base64.b64encode(raw).decode()


# ─── E2E decrypt (matches web/lib/e2e.ts sealToDevice) ────────────────────────

def unseal(priv, sealed: dict) -> str:
    epk = ec.EllipticCurvePublicKey.from_encoded_point(
        ec.SECP256R1(), base64.b64decode(sealed["epk"])
    )
    shared = priv.exchange(ec.ECDH(), epk)
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=E2E_SALT, info=E2E_INFO).derive(shared)
    pt = AESGCM(key).decrypt(
        base64.b64decode(sealed["iv"]), base64.b64decode(sealed["ct"]), None
    )
    return pt.decode("utf-8")


# ─── HTTP helpers ─────────────────────────────────────────────────────────────

def _req(method, url, headers=None, body=None, timeout=40):
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"error": raw.decode(errors="replace")}


# ─── main loop ────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=os.environ.get("AURAL_CLOUD_URL", "http://localhost:3000"))
    ap.add_argument("--reset", action="store_true", help="forget cached identity and re-register")
    args = ap.parse_args()
    base = args.base_url.rstrip("/")

    state = load_state(args.reset)
    priv = serialization.load_pem_private_key(state["priv_pem"].encode(), password=None)
    dev_headers = {"X-Device-Id": state["device_id"], "X-Device-Secret": state["secret"]}

    print(f"Mock device id: {state['device_id']}")
    print(f"Cloud base:     {base}")

    # 1. register
    st, resp = _req("POST", f"{base}/api/devices/register", body={
        "device_id": state["device_id"],
        "secret": state["secret"],
        "pubkey": pubkey_b64(priv),
        "fw_version": "mock-0.1",
    })
    if st != 200:
        print(f"register failed: {st} {resp}")
        sys.exit(1)
    paired = bool(resp.get("paired"))
    print(f"registered (paired={paired})")

    # 2. request a pairing code if not yet paired
    if not paired:
        st, resp = _req("POST", f"{base}/api/pair/code", headers=dev_headers, body={})
        if st != 200:
            print(f"pair/code failed: {st} {resp}")
            sys.exit(1)
        code = resp["code"]
        print("\n" + "=" * 40)
        print(f"   PAIRING CODE:  {code}")
        print(f"   buka {base}/pair dan masukkan kode di atas")
        print("=" * 40 + "\n")

    # 3 + 4. heartbeat + long-poll for commands
    last_hb = 0.0
    print("polling for config… (Ctrl+C to stop)")
    while True:
        now = time.time()
        if now - last_hb > 20:
            _req("POST", f"{base}/api/heartbeat", headers=dev_headers, body={
                "status": {"mode": "explorer", "wifi": "MockNet", "battery": 88, "online": True},
            })
            last_hb = now

        st, resp = _req("GET", f"{base}/api/poll?device_id={state['device_id']}", headers=dev_headers)
        if st == 204 or not resp:
            continue
        if st != 200:
            print(f"poll error: {st} {resp}")
            time.sleep(3)
            continue

        cmd = resp.get("command")
        if not cmd:
            continue
        payload = cmd.get("payload", {})
        config = payload.get("config", {})
        secrets = payload.get("secrets", {})

        print("\n── command received ──────────────────────────")
        print(f"config: {json.dumps(config, ensure_ascii=False)}")
        for name, sealed in secrets.items():
            try:
                value = unseal(priv, sealed)
                masked = value[:4] + "…" + value[-4:] if len(value) > 8 else "(short)"
                print(f"secret {name}: DECRYPTED OK → {masked} (len={len(value)})")
            except Exception as e:
                print(f"secret {name}: DECRYPT FAILED → {e}")
        print("──────────────────────────────────────────────\n")

        _req("POST", f"{base}/api/ack", headers=dev_headers, body={"command_id": cmd["id"]})
        print(f"acked {cmd['id']}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nstopped.")

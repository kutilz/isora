#!/usr/bin/env python3
"""
set_api_key.py — Encrypt and store an API key on the device.

Run this on the device console (or via SSH) after deploy to embed a
provider key in /root/config.json without leaving it in plaintext.

Usage:
    python3 set_api_key.py --provider openai --key sk-...
    python3 set_api_key.py --provider gemini --key AIza...
    python3 set_api_key.py --provider claude --key sk-ant-...
    python3 set_api_key.py --lock     # mark keys as immutable from web
    python3 set_api_key.py --unlock   # allow web edits again
    python3 set_api_key.py --show     # report which keys are present

Key is encrypted with a device-derived symmetric key (see
device/utils/secure_keys.py) — moving the SD card to another machine
will not yield a working key.
"""

import argparse
import json
import sys
from pathlib import Path

# Allow importing device modules
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "device"))

CONFIG_PATH = Path("/root/config.json")


def _load_cfg() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {}


def _save_cfg(data: dict):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=2)


def main():
    p = argparse.ArgumentParser(description="Encrypt and store API keys.")
    p.add_argument("--provider", choices=["openai", "gemini", "claude"])
    p.add_argument("--key",      help="Plaintext API key to encrypt and store.")
    p.add_argument("--lock",     action="store_true",
                   help="Lock api keys (web UI can no longer overwrite).")
    p.add_argument("--unlock",   action="store_true",
                   help="Unlock api keys (allow web edits).")
    p.add_argument("--show",     action="store_true",
                   help="Print which keys are present + lock state.")
    args = p.parse_args()

    from utils.secure_keys import encrypt, decrypt, is_ciphertext

    data = _load_cfg()

    if args.show:
        for prov in ("openai", "gemini", "claude"):
            enc = data.get(f"{prov}_api_key_enc", "")
            pla = data.get(f"{prov}_api_key", "")
            state = ("encrypted" if enc else
                     "plaintext" if pla else
                     "unset")
            print(f"  {prov:6s}  {state}")
        print(f"  lock    {'ON' if data.get('api_keys_locked') else 'off'}")
        return

    if args.unlock:
        data["api_keys_locked"] = False
        _save_cfg(data)
        print("Keys unlocked — web UI can now edit them.")
        return

    if args.provider and args.key:
        enc = encrypt(args.key)
        # sanity: round-trip
        if decrypt(enc) != args.key:
            print("ERROR: encrypt/decrypt round-trip mismatch. Aborting.")
            sys.exit(2)
        data[f"{args.provider}_api_key_enc"] = enc
        data[f"{args.provider}_api_key"]     = ""
        _save_cfg(data)
        print(f"OK: {args.provider}_api_key_enc stored "
              f"(len={len(enc)} chars).")

    if args.lock:
        data["api_keys_locked"] = True
        _save_cfg(data)
        print("Keys locked — web UI can no longer overwrite. "
              "Run with --unlock to allow edits again.")


if __name__ == "__main__":
    main()

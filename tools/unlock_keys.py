#!/usr/bin/env python3
"""
unlock_keys.py — Clear the api_keys_locked flag.

This is the "procedure" the web UI mentions when refusing to overwrite
locked keys. It exists as a separate script (rather than a /unlock
HTTP route) so that an attacker on the local network cannot disable
the lock — physical/SSH access to the device is required.

Usage:
    python3 unlock_keys.py
    python3 unlock_keys.py --confirm   # skip the y/N prompt
"""

import argparse
import json
import sys
from pathlib import Path

CONFIG_PATH = Path("/root/config.json")


def main():
    p = argparse.ArgumentParser(description="Clear the api_keys_locked flag.")
    p.add_argument("--confirm", action="store_true",
                   help="Skip interactive confirmation.")
    args = p.parse_args()

    if not CONFIG_PATH.exists():
        print(f"No config file at {CONFIG_PATH} — nothing to unlock.")
        return

    with open(CONFIG_PATH) as f:
        data = json.load(f)

    if not data.get("api_keys_locked"):
        print("Already unlocked. No change.")
        return

    if not args.confirm:
        ans = input("Unlock API keys for web edits? [y/N]: ").strip().lower()
        if ans != "y":
            print("Aborted.")
            sys.exit(1)

    data["api_keys_locked"] = False
    with open(CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=2)
    print("Keys unlocked — web UI can now edit API keys.")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
Build, sign and publish a device release for the auto-updater.

    python tools/release.py keygen                 # once: create the signing key
    python tools/release.py build                  # dist/isora-device-<v>.tar.gz + manifest
    python tools/release.py publish                # GitHub release device-v<v> (marked latest)
    python tools/release.py verify                 # re-check dist/ against the device's key

How a device updates (core/updater.py): once a day it reads
  https://github.com/kutilz/isora/releases/latest/download/isora-device.json
checks the signature against the public key compiled into core/updater.py,
downloads the tarball, checks its SHA-256, unpacks it next to the running
version and switches at the next quiet moment. A version that does not
become healthy is rolled back (device/system/release.py).

The PRIVATE key lives outside the repo, at ~/.isora/release-signing-key.json.
Whoever holds it can put code on every unit; lose it and units only take new
releases after a deploy that carries a new public key. Back it up offline.

Versions are dates: 2026.10.21.1, 2026.10.21.2, ... A unit deployed with
tools/deploy.py or tools/run.py carries "<latest tag>+dev.<time>", so it is
only replaced by a release NEWER than the one it was developed on.
"""

import argparse
import base64
import datetime
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEVICE_DIR = os.path.join(ROOT, "device")
DIST = os.path.join(ROOT, "dist")
KEY_PATH = os.path.join(os.path.expanduser("~"), ".isora", "release-signing-key.json")
REPO = "kutilz/isora"
TAG_PREFIX = "device-v"
MANIFEST_NAME = "isora-device.json"

sys.path.insert(0, DEVICE_DIR)
from utils import release_sig  # noqa: E402

# Not shipped to units: tests, the Preact source + node_modules (the built
# output in server/static/app/ is what the device serves), caches.
_EXCLUDE_DIRS = {"tests", "__pycache__", "node_modules", ".pytest_cache"}
_EXCLUDE_SUFFIX = (".pyc", ".pyo")


def _git(*args) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          text=True).stdout.strip()


def _parse(v):
    try:
        return tuple(int(p) for p in v.split("+", 1)[0].split("."))
    except ValueError:
        return None


def latest_tag_version() -> str:
    """Newest device-v* tag known locally ("0" if none)."""
    best = None
    for tag in _git("tag", "-l", TAG_PREFIX + "*").splitlines():
        v = tag[len(TAG_PREFIX):]
        if _parse(v) and (best is None or _parse(v) > _parse(best)):
            best = v
    return best or "0"


def dev_version() -> str:
    """What tools/deploy.py and tools/run.py stamp into /root/isora/VERSION."""
    return "%s+dev.%s" % (latest_tag_version(),
                          datetime.datetime.now().strftime("%Y%m%dT%H%M%S"))


def next_version() -> str:
    today = datetime.date.today().strftime("%Y.%m.%d")
    _git("fetch", "--tags", "--quiet")
    used = [t for t in _git("tag", "-l", TAG_PREFIX + today + ".*").splitlines()]
    n = max([int(t.rsplit(".", 1)[1]) for t in used if t.rsplit(".", 1)[1].isdigit()] or [0])
    return "%s.%d" % (today, n + 1)


def _files():
    for root, dirs, files in os.walk(DEVICE_DIR):
        rel_root = os.path.relpath(root, DEVICE_DIR)
        dirs[:] = sorted(d for d in dirs if d not in _EXCLUDE_DIRS
                         and not (rel_root == "server" and d == "src"))
        for name in sorted(files):
            if name.endswith(_EXCLUDE_SUFFIX) or name == "VERSION":
                continue
            full = os.path.join(root, name)
            yield full, os.path.relpath(full, DEVICE_DIR).replace("\\", "/")


def _load_key() -> dict:
    if not os.path.exists(KEY_PATH):
        sys.exit("No signing key at %s — run `python tools/release.py keygen` first."
                 % KEY_PATH)
    with open(KEY_PATH) as f:
        return json.load(f)


def _device_pubkey() -> str:
    """The public key compiled into core/updater.py (what units will check)."""
    import re
    src = open(os.path.join(DEVICE_DIR, "core", "updater.py"), encoding="utf-8").read()
    m = re.search(r'^RELEASE_PUBKEY_B64\s*=\s*"([^"]+)"', src, re.M)
    return m.group(1) if m else ""


def cmd_keygen(args):
    if os.path.exists(KEY_PATH) and not args.force:
        sys.exit("A key already exists at %s (use --force to replace it — every "
                 "unit would then need a redeploy to trust the new one)." % KEY_PATH)
    priv, pub = release_sig.generate_keypair()
    os.makedirs(os.path.dirname(KEY_PATH), exist_ok=True)
    with open(KEY_PATH, "w") as f:
        json.dump({"d": priv, "pub": pub,
                   "created": datetime.datetime.now().isoformat(timespec="seconds")}, f)
    try:
        os.chmod(KEY_PATH, 0o600)
    except OSError:
        pass
    print("Private key: %s  (back it up; never commit it)" % KEY_PATH)
    print("Public key (put in device/core/updater.py RELEASE_PUBKEY_B64):\n%s" % pub)


def cmd_build(args):
    dirty = _git("status", "--porcelain", "--", "device")
    if dirty and not args.allow_dirty:
        sys.exit("device/ has uncommitted changes — commit first, or pass --allow-dirty "
                 "(a release should be exactly a commit).")
    key = _load_key()
    if _device_pubkey() != key["pub"]:
        sys.exit("The signing key does not match RELEASE_PUBKEY_B64 in core/updater.py; "
                 "units would reject this release.")
    version = args.version or next_version()
    if _parse(version) is None or not all(c.isdigit() or c == "." for c in version):
        sys.exit("version must look like 2026.10.21.1")
    os.makedirs(DIST, exist_ok=True)
    name = "isora-device-%s.tar.gz" % version
    path = os.path.join(DIST, name)

    count = 0
    with tarfile.open(path, "w:gz", format=tarfile.PAX_FORMAT) as tf:
        for full, rel in _files():
            info = tf.gettarinfo(full, arcname=rel)
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            info.mode = 0o755 if (rel.endswith(".sh") or rel == "system/S31wifiroam") else 0o644
            with open(full, "rb") as f:
                data = f.read()
            if rel.startswith("system/") and not rel.endswith(".py"):
                data = data.replace(b"\r\n", b"\n")     # busybox sh needs LF
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
            count += 1
        vinfo = tarfile.TarInfo("VERSION")
        vbytes = (version + "\n").encode()
        vinfo.size = len(vbytes)
        vinfo.mode = 0o644
        vinfo.mtime = int(datetime.datetime.now().timestamp())
        tf.addfile(vinfo, io.BytesIO(vbytes))

    blob = open(path, "rb").read()
    digest = hashlib.sha256(blob).hexdigest()
    sig = release_sig.sign(key["d"], release_sig.release_message(version, digest, len(blob)))
    manifest = {
        "format": 1,
        "version": version,
        "file": name,
        "url": "https://github.com/%s/releases/download/%s%s/%s"
               % (REPO, TAG_PREFIX, version, name),
        "size": len(blob),
        "sha256": digest,
        "sig": base64.b64encode(sig).decode(),
        "commit": _git("rev-parse", "HEAD"),
    }
    with open(os.path.join(DIST, MANIFEST_NAME), "w") as f:
        json.dump(manifest, f, indent=2)
    print("Built %s: %d files, %.1f KB, sha256 %s" % (name, count + 1, len(blob) / 1024, digest[:16]))
    print("Manifest: %s" % os.path.join(DIST, MANIFEST_NAME))


def _read_manifest() -> dict:
    with open(os.path.join(DIST, MANIFEST_NAME)) as f:
        return json.load(f)


def cmd_verify(args):
    m = _read_manifest()
    blob = open(os.path.join(DIST, m["file"]), "rb").read()
    ok_hash = hashlib.sha256(blob).hexdigest() == m["sha256"] and len(blob) == m["size"]
    ok_sig = release_sig.verify(_device_pubkey(), release_sig.release_message(
        m["version"], m["sha256"], m["size"]), base64.b64decode(m["sig"]))
    print("version %s  hash %s  signature %s" % (m["version"], "OK" if ok_hash else "BAD",
                                                  "OK" if ok_sig else "BAD"))
    if not (ok_hash and ok_sig):
        sys.exit(1)


def cmd_publish(args):
    cmd_verify(args)
    m = _read_manifest()
    tag = TAG_PREFIX + m["version"]
    files = [os.path.join(DIST, m["file"]), os.path.join(DIST, MANIFEST_NAME)]
    notes = ("Device release %s (commit %s). Units pick it up within a day "
             "and switch at their next quiet moment." % (m["version"], m["commit"][:10]))
    cmd = ["gh", "release", "create", tag, *files, "--repo", REPO,
           "--title", "I-Sora device %s" % m["version"], "--notes", notes,
           "--target", m["commit"], "--latest"]
    print(" ".join(cmd))
    if args.dry_run:
        return
    subprocess.run(cmd, check=True)
    _git("fetch", "--tags", "--quiet")


def main():
    p = argparse.ArgumentParser(description="I-Sora device releases")
    sub = p.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("keygen")
    k.add_argument("--force", action="store_true")
    b = sub.add_parser("build")
    b.add_argument("--version")
    b.add_argument("--allow-dirty", action="store_true")
    sub.add_parser("verify")
    pub = sub.add_parser("publish")
    pub.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    {"keygen": cmd_keygen, "build": cmd_build, "verify": cmd_verify,
     "publish": cmd_publish}[args.cmd](args)


if __name__ == "__main__":
    main()

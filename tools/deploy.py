# -*- coding: utf-8 -*-
"""
Deploy Script - Upload project ke MaixCAM via SCP/SFTP.
Jalankan dari PC setelah edit kode di Cursor.

Requires: pip install paramiko

Usage:
    python tools/deploy.py                         # Deploy device/ ke MaixCAM
    python tools/deploy.py --audio-only            # Hanya upload audio/
    python tools/deploy.py --host 192.168.1.100    # Custom IP
    python tools/deploy.py --dry-run               # Preview tanpa upload
"""

import os
import sys
import argparse

# Load .env dari project root kalau ada
_env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

# Default MaixCAM connection
# Override via .env file atau --host flag
DEFAULT_HOST = os.environ.get("AURAL_MAIX_HOST", "maixcam.local")
DEFAULT_PORT = int(os.environ.get("AURAL_MAIX_PORT", "22"))
DEFAULT_USER = os.environ.get("AURAL_MAIX_USER", "root")
DEFAULT_PASS = os.environ.get("AURAL_MAIX_PASS", "root")

REMOTE_DEVICE_DIR = "/root/aural-ai/"
REMOTE_AUDIO_DIR  = "/root/audio/"

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
DEVICE_DIR   = os.path.join(PROJECT_ROOT, "device")
AUDIO_DIR    = os.path.join(PROJECT_ROOT, "audio")

EXCLUDE_PATTERNS = {
    "__pycache__", ".pyc", ".pyo", ".DS_Store", "*.egg-info",
    "node_modules", ".git",
}


def should_exclude(path):
    for pat in EXCLUDE_PATTERNS:
        if pat.startswith("*"):
            if path.endswith(pat[1:]):
                return True
        else:
            if pat in path:
                return True
    return False


def deploy_directory(sftp, local_dir, remote_dir, dry_run=False):
    """Upload seluruh isi local_dir ke remote_dir secara rekursif."""
    uploaded = 0

    for root, dirs, files in os.walk(local_dir):
        # Exclude dirs
        dirs[:] = [d for d in dirs if not should_exclude(d)]

        rel_root = os.path.relpath(root, local_dir)
        remote_root = os.path.join(remote_dir, rel_root).replace("\\", "/")
        if remote_root.endswith("/."):
            remote_root = remote_root[:-2]

        if not dry_run:
            try:
                sftp.mkdir(remote_root)
            except IOError:
                pass  # Dir sudah ada

        for filename in files:
            if should_exclude(filename):
                continue

            local_path = os.path.join(root, filename)
            remote_path = os.path.join(remote_root, filename).replace("\\", "/")

            print(f"  -> {remote_path}")
            if not dry_run:
                sftp.put(local_path, remote_path)
            uploaded += 1

    return uploaded


def main():
    parser = argparse.ArgumentParser(description="AuralAI Deploy Script")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--password", default=DEFAULT_PASS)
    parser.add_argument("--audio-only", action="store_true", help="Hanya upload folder audio/")
    parser.add_argument("--dry-run", action="store_true", help="Preview saja tanpa upload")
    args = parser.parse_args()

    try:
        import paramiko
    except ImportError:
        print("ERROR: paramiko tidak terinstall. Jalankan: pip install paramiko")
        sys.exit(1)

    print(f"AuralAI Deploy -> {args.user}@{args.host}:{args.port}")
    if args.dry_run:
        print("DRY RUN MODE - tidak ada yang di-upload\n")

    if not args.dry_run:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            print(f"Connecting to {args.host}...")
            client.connect(
                hostname=args.host,
                port=args.port,
                username=args.user,
                password=args.password,
                timeout=10,
            )
            print("Connected!\n")
        except Exception as e:
            print(f"ERROR: Gagal connect ke MaixCAM: {e}")
            print("Pastikan MaixCAM menyala dan terhubung ke WiFi yang sama.")
            sys.exit(1)

        sftp = client.open_sftp()
    else:
        sftp = None
        client = None

    total = 0

    if args.audio_only:
        print(f"Uploading audio/ -> {REMOTE_AUDIO_DIR}")
        n = deploy_directory(sftp, AUDIO_DIR, REMOTE_AUDIO_DIR, dry_run=args.dry_run)
        total += n
    else:
        print(f"Uploading device/ -> {REMOTE_DEVICE_DIR}")
        n = deploy_directory(sftp, DEVICE_DIR, REMOTE_DEVICE_DIR, dry_run=args.dry_run)
        total += n

        # Upload audio juga jika ada file
        audio_files = [f for f in os.listdir(AUDIO_DIR) if f.endswith(".wav")]
        if audio_files:
            print(f"\nUploading audio/ ({len(audio_files)} files) -> {REMOTE_AUDIO_DIR}")
            n = deploy_directory(sftp, AUDIO_DIR, REMOTE_AUDIO_DIR, dry_run=args.dry_run)
            total += n

    if not args.dry_run and not args.audio_only:
        print(f"\nMembuat direktori logs di MaixCAM...")
        try:
            client.exec_command("mkdir -p /root/logs /root/models /root/audio /root/captures")
        except Exception:
            pass

    if sftp:
        sftp.close()
    if client:
        client.close()

    print(f"\nDeploy selesai! {total} file {'(dry run)' if args.dry_run else 'ter-upload'}.")
    if not args.dry_run:
        print(f"\nJalankan di MaixCAM:")
        print(f"  cd {REMOTE_DEVICE_DIR} && python main.py")
        print(f"  # Companion PC: python aural_maix.py (set AURAL_COMPANION_HOST)")
        print(f"\nAtau via MaixVision: buka main.py atau aural_maix.py -> Run")


if __name__ == "__main__":
    main()

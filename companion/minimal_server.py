#!/usr/bin/env python3
"""
Server HTTP minimal untuk isolasi koneksi MaixCAM <-> PC.
Tidak pakai OpenAI — hanya Flask + JSON.

PC:
  python companion/minimal_server.py
  python companion/minimal_server.py 9000

MaixCAM (WiFi sudah dapat IP):
  export AURAL_PROBE_HOST=<IPv4 Wi-Fi PC, BUKAN 127.0.0.1>
  export AURAL_PROBE_PORT=8765
  python device/network_probe.py

Catatan: IP seperti 10.207.x.x sering dari WSL2 / virtual adapter — MaixCAM di WiFi
biasanya TIDAK bisa menjangkau IP itu. Pakai IPv4 dari adapter "Wi-Fi" / "Ethernet"
di ipconfig (Windows) atau `hostname -I` (Linux native, bukan di dalam WSL).
"""

from __future__ import annotations

import argparse
import socket
import sys

from flask import Flask, jsonify, request

app = Flask(__name__)


@app.get("/")
def root():
    return jsonify({"service": "aural-network-probe", "ok": True})


@app.get("/health")
def health():
    return jsonify({"ok": True, "msg": "health"})


@app.post("/ping")
def ping():
    body = request.get_json(silent=True) or {}
    return jsonify({"ok": True, "echo": body})


def _guess_lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "?"
    finally:
        s.close()


def _likely_not_reachable_from_wifi_lan(ip: str) -> bool:
    """IP yang sering dipilih salah: WSL/Hyper-V/dev tunnel — MaixCAM di WiFi tidak punya rute."""
    if not ip or ip in ("?", "127.0.0.1"):
        return False
    parts = ip.split(".")
    if len(parts) != 4 or not all(p.isdigit() for p in parts):
        return False
    a, b = int(parts[0]), int(parts[1])
    if a == 10 and b == 207:
        return True
    if a == 172 and 16 <= b <= 31:
        return True
    return False


def _print_windows_ipconfig_ipv4_lines():
    if sys.platform != "win32":
        return
    try:
        import subprocess

        cp = subprocess.run(
            ["ipconfig"],
            capture_output=True,
            text=True,
            encoding=sys.stdout.encoding or "utf-8",
            errors="replace",
            timeout=10,
        )
        text = cp.stdout or ""
        hits = [ln.rstrip() for ln in text.splitlines() if "IPv4" in ln and "127.0.0.1" not in ln]
        if not hits:
            return
        print("\n  >>> ipconfig — pilih IPv4 yang **satu subnet** dengan MaixCAM (biasa 192.168.x.x):")
        for ln in hits[:16]:
            print(f"      {ln}")
        print()
    except Exception:
        pass


def main():
    p = argparse.ArgumentParser(description="Minimal probe server for MaixCAM connectivity test")
    p.add_argument("port", nargs="?", type=int, default=8765, help="Listen port (default 8765)")
    args = p.parse_args()
    port = args.port
    lip = _guess_lan_ip()
    print("=" * 56)
    print("  AuralAI — minimal probe server (Flask)")
    print(f"  Listen   : 0.0.0.0:{port}  (semua interface)")
    print(f"  IP perkiraan (rute ke 8.8.8.8): {lip}")
    if _likely_not_reachable_from_wifi_lan(lip):
        print()
        print("  *** PERINGATAN ***")
        print(f"  Alamat {lip} biasanya BUKAN jaringan Wi-Fi yang dipakai MaixCAM.")
        print("  Kalau MaixCAM error [Errno 101] Network unreachable → di MaixCAM set")
        print("  AURAL_PROBE_HOST ke IPv4 adapter **Wi-Fi** PC (bukan IP ini).")
        _print_windows_ipconfig_ipv4_lines()
        print('  Contoh benar: export AURAL_PROBE_HOST="192.168.1.5"')
        print()
    print("  Di MaixCAM (hanya jika IP di atas = subnet yang sama dengan MaixCAM):")
    print(f'    export AURAL_PROBE_HOST="{lip}"')
    print(f"    export AURAL_PROBE_PORT={port}")
    print("    python device/network_probe.py")
    print("  Uji dari browser PC: http://127.0.0.1:{}/health".format(port))
    print("=" * 56)
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False)


if __name__ == "__main__":
    main()

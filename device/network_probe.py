"""
Uji koneksi HTTP MaixCAM → PC (isolasi, tanpa kamera/YOLO).

Di PC jalankan dulu:
  python companion/minimal_server.py

Di MaixCAM:
  export AURAL_PROBE_HOST=192.168.x.x    # IPv4 Wi-Fi/Ethernet PC (satu subnet dengan MaixCAM)
  export AURAL_PROBE_PORT=8765
  python device/network_probe.py

Bisa juga pakai variabel companion yang sama:
  export AURAL_COMPANION_HOST=192.168.x.x
  export AURAL_COMPANION_PORT=8765
  python device/network_probe.py

Opsional — sambung WiFi dari script (pola MaixPy resmi, timeout 60s):
  export AURAL_WIFI_SSID=nama_ap
  export AURAL_WIFI_PASSWORD=...

Kalau udhcpc hanya «discover» terus: sambung lewat **Settings → WiFi** di MaixCAM
(kadang DHCP stabil hanya dari GUI), lalu jalankan probe **tanpa** AURAL_WIFI_*.
"""

from __future__ import annotations

import os
import socket
import sys

try:
    import requests
except ImportError:
    print("ERROR: modul requests tidak ada (MaixPy biasanya sudah menyertakan).")
    sys.exit(1)

HOST = os.environ.get("AURAL_PROBE_HOST") or os.environ.get("AURAL_COMPANION_HOST", "")
PORT = int(os.environ.get("AURAL_PROBE_PORT") or os.environ.get("AURAL_COMPANION_PORT", "8765"))


def _ipv4_parts(s):
    try:
        p = [int(x) for x in s.strip().split(".")]
        return p if len(p) == 4 and all(0 <= n <= 255 for n in p) else None
    except (ValueError, AttributeError):
        return None


def _same_subnet24(local: str, remote: str) -> bool:
    a, b = _ipv4_parts(local), _ipv4_parts(remote)
    if not a or not b:
        return False
    return a[:3] == b[:3]


def _guess_outbound_ipv4():
    """IP sumber jika ada rute ke internet (kadang terisi walau Wifi().get_ip() kosong)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return ""
    finally:
        s.close()


def _optional_wifi_connect_from_env():
    """Set AURAL_WIFI_SSID (+ PASSWORD): pakai wifi_connect.py (sama contoh MaixPy)."""
    ssid = (os.environ.get("AURAL_WIFI_SSID") or "").strip()
    if not ssid:
        return
    pwd = os.environ.get("AURAL_WIFI_PASSWORD", "") or ""
    try:
        from wifi_connect import connect_wifi

        print(f"[probe] Menyambung WiFi (timeout 60s): {ssid!r} ...")
        ip = connect_wifi(ssid, pwd, timeout_s=60)
        print(f"[probe] WiFi OK, IP: {ip!r}\n")
    except Exception as ex:
        print(f"[probe] WiFi dari script gagal: {ex}")
        print(
            "[probe] Coba: **Settings → WiFi** di MaixCAM sampai dapat IP, "
            "lalu unset AURAL_WIFI_* dan jalankan probe lagi.\n"
        )


def _print_maix_ip_and_subnet_check(pc_host: str) -> str:
    """Cetak status IP; kembalikan IP efektif (get_ip atau outbound) atau \"\"."""
    my_ip = ""
    try:
        from maix import network

        w = network.wifi.Wifi()
        my_ip = (w.get_ip() or "").strip()
    except Exception as e:
        print(f"(Wifi API: {e})")

    sock_ip = _guess_outbound_ipv4().strip()
    print(f"IP MaixCAM (Wifi().get_ip()): {my_ip or '(kosong)'}")
    print(f"IP sumber outbound (socket->8.8.8.8): {sock_ip or '(kosong — tidak ada rute/default gateway)'}")
    effective = my_ip or sock_ip

    if not effective:
        print()
        print("*** MaixCAM BELUM PUNYA IP Wi-Fi YANG DIPAKAI UNTUK INTERNET ***")
        print(
            "Tanpa IP, koneksi ke PC mana pun akan errno 101 (network unreachable).\n"
            "• Sambung Wi-Fi lewat aplikasi **Settings** di MaixCAM (QR / scan SSID), atau\n"
            "• Jalankan probe dengan env: AURAL_WIFI_SSID dan AURAL_WIFI_PASSWORD (script akan connect dulu).\n"
            "Lihat: dokumentasi MaixPy «Network Settings» (Wifi().connect)."
        )
        print("***\n")
        return ""

    if my_ip and sock_ip and my_ip != sock_ip:
        print(f"  (Peringatan: get_ip={my_ip} != outbound={sock_ip} — untuk subnet pakai: {effective})")

    if not pc_host:
        return effective

    if not _same_subnet24(effective, pc_host):
        m3 = _ipv4_parts(effective)
        p3 = _ipv4_parts(pc_host)
        m_pref = f"{m3[0]}.{m3[1]}.{m3[2]}.0/24" if m3 else "?"
        p_pref = f"{p3[0]}.{p3[1]}.{p3[2]}.0/24" if p3 else "?"
        print()
        print("*** SUBNET BEDA (penyebab errno 101 yang paling umum) ***")
        print(f"  MaixCAM (efektif): {effective}  → /24: {m_pref}")
        print(f"  PC               : {pc_host}  → /24: {p_pref}")
        print(
            "  Keduanya harus awalan 3 oktet SAMA (contoh sama-sama 192.168.1.*).\n"
            "  Solusi: sambungkan PC dan MaixCAM ke **router / hotspot yang sama**,\n"
            "  lalu di PC jalankan ipconfig lagi dan pakai IPv4 yang **satu keluarga** dengan IP MaixCAM di atas."
        )
        print("***\n")
    else:
        print("  (Oktet ke-1..3 sama dengan PC — subnet /24 cocok; lanjut uji HTTP.)\n")
    return effective


def _hint_unreachable(host: str, err: str) -> None:
    if "101" not in err and "unreachable" not in err.lower() and "Network" not in err:
        return
    print()
    print("--- Petunjuk errno 101 / Network unreachable ---")
    print(f"Host yang dicoba: {host}")
    print(
        "Ini artinya **stack IP MaixCAM tidak punya rute** ke alamat itu.\n"
        "Bukan bug script: biasanya **PC dan MaixCAM beda subnet**, atau **isolasi AP** (guest WiFi)."
    )
    if host.startswith("10.207."):
        print(
            "\nCatatan: 10.207.x.x kadang adapter khusus; kalau ipconfig Wi-Fi memang begitu,\n"
            "pastikan **MaixCAM juga dapat IP 10.207.x.x** dari router yang sama. "
            "Kalau MaixCAM malah 192.168.x.x → tetap beda subnet → gagal."
        )
    print(
        "\nCek: bandingkan **IP efektif MaixCAM** (get_ip atau outbound) dengan IP PC.\n"
        "• Sama 3 angka pertama (mis. 192.168.1.* dan 192.168.1.*) → OK untuk /24.\n"
        "• Beda (mis. 192.168.4.* vs 10.207.255.*) → pakai hotspot ponsel ke **dua** perangkat, atau SSID router yang sama.\n"
        "• Matikan *client isolation* / guest network jika ada.\n"
        "• Firewall PC: izinkan inbound TCP port yang dipakai (8765 / 5000)."
    )
    print("-----------------------------------------------")


def main():
    if not HOST:
        print("ERROR: set AURAL_PROBE_HOST atau AURAL_COMPANION_HOST ke IPv4 PC (bukan 127.0.0.1).")
        print("  Contoh: export AURAL_PROBE_HOST=192.168.1.50")
        sys.exit(1)

    _optional_wifi_connect_from_env()

    base = f"http://{HOST}:{PORT}"
    print(f"AuralAI network probe → {base}\n")
    _effective_ip = _print_maix_ip_and_subnet_check(HOST)

    last_err = ""
    ok_count = 0
    for method, path in (("GET", "/health"), ("GET", "/")):
        url = base + path
        try:
            r = requests.request(method, url, timeout=8)
            print(f"OK  {method} {path}  status={r.status_code}  body={r.text[:300]}")
            ok_count += 1
        except Exception as e:
            last_err = str(e)
            print(f"FAIL {method} {path}  {type(e).__name__}: {e}")

    try:
        r = requests.post(base + "/ping", json={"from": "maixcam", "test": True}, timeout=8)
        print(f"OK  POST /ping  status={r.status_code}  body={r.text[:300]}")
        ok_count += 1
    except Exception as e:
        last_err = str(e)
        print(f"FAIL POST /ping  {type(e).__name__}: {e}")

    if ok_count < 3:
        _hint_unreachable(HOST, last_err)
        if not _effective_ip:
            print(
                "(Ringkas) Pastikan WiFi MaixCAM benar-benar online: Settings → WiFi, "
                "atau set AURAL_WIFI_SSID / AURAL_WIFI_PASSWORD lalu jalankan ulang probe.\n"
            )

    print("\nSelesai. Jika semua OK, companion utama bisa dipakai dengan host/port yang sama.")


if __name__ == "__main__":
    main()

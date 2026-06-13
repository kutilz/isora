"""
Koneksi WiFi — pola resmi MaixPy (dokumentasi «Network Settings»).

Hanya dipakai di MaixCAM. Contoh setara:

    from maix import network, err
    w = network.wifi.Wifi()
    e = w.connect(SSID, PASSWORD, wait=True, timeout=60)
    err.check_raise(e, "connect wifi failed")

Di lapangan, **Settings → WiFi** di perangkat sering lebih andal daripada skrip
kalau DHCP (udhcpc) hanya discover terus — sambung manual dulu lalu jalankan app.
"""

from __future__ import annotations


def connect_wifi(ssid: str, password: str, *, timeout_s: int = 60) -> str:
    """
    Sambung ke AP dan kembalikan IP (string), atau raise jika gagal.
    """
    from maix import network, err

    w = network.wifi.Wifi()
    e = w.connect(ssid, password, wait=True, timeout=timeout_s)
    err.check_raise(e, "connect wifi failed")
    return (w.get_ip() or "").strip()

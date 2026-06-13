"""
Headless MaixCAM client (tanpa layar).

Fungsi:
- Kirim preview frame ke companion (/api/frame_preview) agar dashboard punya live view.
- Poll command dari companion (/api/command).
  - {type:"set_mode", mode:N}  -> update mode lokal + notify companion (/api/mode)
  - {type:"scan"}              -> capture 1 frame dan kirim ke /api/frame dengan task sesuai mode:
                                 mode 2=ocr, mode 3=describe, mode 4=qris

Env yang dipakai (set di MaixCAM):
  AURAL_COMPANION_HOST=192.168.x.x
  AURAL_COMPANION_PORT=5000
  (opsional) AURAL_WIFI_SSID / AURAL_WIFI_PASSWORD

Jalankan:
  python headless_client.py
"""

from __future__ import annotations

import base64
import os
import time

from maix import app, camera, image, network  # type: ignore

try:
    import requests  # type: ignore
except ImportError:
    requests = None
    print("ERROR: modul requests tidak ditemukan di MaixCAM.")


SSID = (os.environ.get("AURAL_WIFI_SSID") or "").strip()
PASSWORD = os.environ.get("AURAL_WIFI_PASSWORD") or ""
HOST_IP = (os.environ.get("AURAL_COMPANION_HOST") or "").strip()
HOST_PORT = int(os.environ.get("AURAL_COMPANION_PORT") or "5000")

API_FRAME = f"http://{HOST_IP}:{HOST_PORT}/api/frame"
API_PREVIEW = f"http://{HOST_IP}:{HOST_PORT}/api/frame_preview"
API_CMD = f"http://{HOST_IP}:{HOST_PORT}/api/command"
API_MODE = f"http://{HOST_IP}:{HOST_PORT}/api/mode"


MODE_OBJECT = 1
MODE_OCR = 2
MODE_SCENE = 3
MODE_QRIS = 4

MODE_NAMES = {
    MODE_OBJECT: "Deteksi Objek",
    MODE_OCR: "Baca Teks (OCR)",
    MODE_SCENE: "Deskripsi Adegan",
    MODE_QRIS: "Scan QRIS",
}


def _connect_wifi_if_needed() -> str:
    """
    Sambung WiFi kalau env SSID diisi.
    Kalau tidak, coba ambil IP yang sudah ada.
    """
    w = network.wifi.Wifi()
    if SSID:
        try:
            from wifi_connect import connect_wifi

            print(f"[wifi] Connecting to {SSID!r} ...")
            ip = connect_wifi(SSID, PASSWORD, timeout_s=60)
            print(f"[wifi] OK IP={ip}")
            return ip
        except Exception as e:
            print(f"[wifi] connect_wifi gagal: {e}")
    try:
        ip = (w.get_ip() or "").strip()
        if ip:
            print(f"[wifi] existing IP={ip}")
        return ip
    except Exception:
        return ""


def _post_json(url: str, payload: dict, timeout_s: float):
    if not requests:
        return None
    try:
        return requests.post(url, json=payload, timeout=timeout_s)
    except Exception:
        return None


def _get_json(url: str, timeout_s: float):
    if not requests:
        return None
    try:
        r = requests.get(url, timeout=timeout_s)
        try:
            return r.json()
        except Exception:
            return None
    except Exception:
        return None


def _img_to_b64_jpeg(img) -> str:
    # Pakai save ke /tmp agar kompatibel dan stabil
    path = "/tmp/aural_headless.jpg"
    img.save(path)
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def main() -> None:
    if not HOST_IP:
        print("ERROR: AURAL_COMPANION_HOST belum diset.")
        return
    if not requests:
        return

    _connect_wifi_if_needed()

    # Dua kamera: preview kecil (ringan) + scan besar (lebih akurat untuk QR).
    prev_w, prev_h = 320, 240
    scan_w, scan_h = 640, 480

    cam_prev = camera.Camera(prev_w, prev_h, image.Format.FMT_RGB888)
    cam_prev.skip_frames(20)
    cam_scan = camera.Camera(scan_w, scan_h, image.Format.FMT_RGB888)
    cam_scan.skip_frames(5)

    current_mode = MODE_QRIS  # default biar langsung relevan
    last_preview_s = 0.0
    preview_interval_s = 0.25  # ~4fps
    last_cmd_poll_s = 0.0
    cmd_poll_interval_s = 0.25

    # Notify companion mode awal
    _post_json(API_MODE, {"mode": current_mode, "name": MODE_NAMES.get(current_mode, "")}, timeout_s=2.0)
    print(f"[headless] start. Companion={HOST_IP}:{HOST_PORT}. Mode={current_mode} ({MODE_NAMES[current_mode]})")

    while not app.need_exit():
        img = cam_prev.read()
        if img is None:
            time.sleep(0.01)
            continue

        now = time.time()

        # 1) Preview stream (dashboard)
        if (now - last_preview_s) >= preview_interval_s:
            last_preview_s = now
            try:
                b64 = _img_to_b64_jpeg(img)
                _post_json(API_PREVIEW, {"image": b64}, timeout_s=0.5)
            except Exception:
                pass

        # 2) Poll command dari companion
        if (now - last_cmd_poll_s) >= cmd_poll_interval_s:
            last_cmd_poll_s = now
            cmd = _get_json(API_CMD, timeout_s=0.8) or {}
            ctype = cmd.get("type")
            if ctype == "set_mode":
                try:
                    m = int(cmd.get("mode") or current_mode)
                except Exception:
                    m = current_mode
                if m != current_mode:
                    current_mode = m
                    _post_json(API_MODE, {"mode": current_mode, "name": MODE_NAMES.get(current_mode, "")}, timeout_s=2.0)
                    print(f"[mode] -> {current_mode} ({MODE_NAMES.get(current_mode,'')})")

            elif ctype == "scan":
                task = None
                if current_mode == MODE_OCR:
                    task = "ocr"
                elif current_mode == MODE_SCENE:
                    task = "describe"
                elif current_mode == MODE_QRIS:
                    task = "qris"

                if not task:
                    print("[scan] diabaikan (mode tidak mendukung scan)")
                    continue

                try:
                    # Saat scan: ambil frame resolusi tinggi agar QR lebih mudah didecode.
                    cap = cam_scan.read()
                    if cap is None:
                        cap = cam_prev.read() or img
                    b64 = _img_to_b64_jpeg(cap)
                    _post_json(API_FRAME, {"image": b64, "task": task}, timeout_s=25.0)
                    print(f"[scan] sent task={task}")
                except Exception as e:
                    print(f"[scan] gagal: {e}")

        time.sleep(0.005)


if __name__ == "__main__":
    main()


"""
AuralAI — loop utama di MaixCAM (MaixPy) + companion PC.

Set env sebelum run (MaixVision / terminal):

  export AURAL_WIFI_SSID="nama_ap"
  export AURAL_WIFI_PASSWORD="password_ap"
  export AURAL_COMPANION_HOST="192.168.x.x"   # IPv4 Wi-Fi PC (satu subnet; bukan IP WSL)
  export AURAL_COMPANION_PORT="5000"

Kalau DHCP dari script macet (udhcpc discover): sambung WiFi lewat **Settings → WiFi**, lalu
unset AURAL_WIFI_* atau biarkan — app akan pakai get_ip() yang sudah ada.

Uji jaringan: companion/minimal_server.py + device/network_probe.py

HTTP: modul `requests` (MaixPy). Tanpa companion, deteksi lokal tetap jalan; OCR/deskripsi butuh PC.
"""

from maix import camera, display, image, nn, app, network, touchscreen  # noqa: F401
import os
import time
import threading
import base64

from detection_calibration import parse_remote_settings


def _apply_ping_settings(resp_json: dict) -> None:
    global _remote_cal
    s = resp_json.get("settings") if isinstance(resp_json, dict) else None
    _remote_cal = parse_remote_settings(s)


_remote_cal = parse_remote_settings({})

try:
    import requests
except ImportError:
    requests = None
    print("WARN: modul requests tidak ditemukan")

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

# ============================================================
# KONFIGURASI (jangan hardcode secret di repo — pakai environment)
# ============================================================
SSID       = os.environ.get("AURAL_WIFI_SSID", "")
PASSWORD   = os.environ.get("AURAL_WIFI_PASSWORD", "")
HOST_IP    = os.environ.get("AURAL_COMPANION_HOST", "192.168.1.1")
HOST_PORT  = int(os.environ.get("AURAL_COMPANION_PORT", "5000"))

API_UPDATE  = f"http://{HOST_IP}:{HOST_PORT}/api/update"
API_FRAME   = f"http://{HOST_IP}:{HOST_PORT}/api/frame"
API_MODE    = f"http://{HOST_IP}:{HOST_PORT}/api/mode"
API_PING    = f"http://{HOST_IP}:{HOST_PORT}/api/ping"
API_PREVIEW = f"http://{HOST_IP}:{HOST_PORT}/api/frame_preview"

CAM_W, CAM_H   = 320, 224
BLUR_THRESHOLD = 50.0  # fallback sebelum ping pertama

# ============================================================
# MODE STATE
# ============================================================
MODE_MENU   = 0
MODE_OBJECT = 1
MODE_TEXT   = 2
MODE_SCENE  = 3

MODE_LABELS = {
    MODE_MENU:   "Menu",
    MODE_OBJECT: "Deteksi Objek",
    MODE_TEXT:   "Baca Teks (OCR)",
    MODE_SCENE:  "Deskripsi Adegan",
}

# ============================================================
# INISIALISASI HARDWARE
# ============================================================
print("AuralAI: Inisialisasi hardware...")

cam  = camera.Camera(CAM_W, CAM_H, image.Format.FMT_RGB888)
disp = display.Display()
ts   = touchscreen.TouchScreen()

SCREEN_W = disp.width()
SCREEN_H = disp.height()
print(f"Layar: {SCREEN_W}x{SCREEN_H}")

# Precompute camera-to-screen mapping (FIT_CONTAIN default)
# min scale agar kamera pas di layar tanpa distorsi
CAM_SCALE  = min(SCREEN_W / CAM_W, SCREEN_H / CAM_H)
CAM_DISP_W = int(CAM_W * CAM_SCALE)
CAM_DISP_H = int(CAM_H * CAM_SCALE)
CAM_OFF_X  = (SCREEN_W - CAM_DISP_W) // 2   # pixel offset kiri
CAM_OFF_Y  = (SCREEN_H - CAM_DISP_H) // 2   # pixel offset atas

# Nav bar: 22px tinggi di bagian bawah gambar kamera
NAV_H     = 22
NAV_SCR_Y = CAM_OFF_Y + int((CAM_H - NAV_H) * CAM_SCALE)  # y layar awal nav bar
NAV_BTN_W = int((CAM_W / 3) * CAM_SCALE)                   # lebar tiap tombol nav di layar

# Header: 22px tinggi di bagian atas gambar kamera
HDR_SCR_Y = CAM_OFF_Y + int(22 * CAM_SCALE)   # y layar akhir header (untuk deteksi back tap)

# Load font
FONT_OK = False
try:
    image.load_font("ui", "/maixapp/share/font/SourceHanSansCN-Regular.otf", size=16)
    image.set_default_font("ui")
    FONT_OK = True
    print("Font UI berhasil dimuat")
except Exception:
    print("WARN: Font UI tidak ditemukan, pakai font default")

# Load YOLOv5
detector_ready = False
detector = None
try:
    detector = nn.YOLOv5(model="/root/models/yolov5s_320x224_int8.cvimodel", dual_buff=True)
    detector_ready = True
    print("YOLOv5 berhasil dimuat")
except Exception as e:
    try:
        detector = nn.YOLOv5(model="/root/models/yolov5s.mud", dual_buff=True)
        detector_ready = True
        print("YOLOv5 berhasil dimuat (.mud)")
    except Exception as e2:
        print(f"WARN: YOLOv5 gagal: {e2}")

# ============================================================
# KONEKSI WIFI (pola MaixPy: wifi_connect.py + err.check_raise, timeout 60s)
# ============================================================
wifi_connected = False
wifi_ip = ""
w = network.wifi.Wifi()
if SSID:
    try:
        from wifi_connect import connect_wifi

        print(f"Menghubungkan ke WiFi (timeout 60s): {SSID!r} ...")
        wifi_ip = connect_wifi(SSID, PASSWORD, timeout_s=60)
        wifi_connected = bool(wifi_ip)
        print(f"WiFi OK — IP MaixCAM: {wifi_ip}")
    except Exception as e:
        print(f"WiFi dari script gagal (mode offline / pakai Settings): {e}")
        try:
            wifi_ip = (w.get_ip() or "").strip()
            wifi_connected = bool(wifi_ip)
            if wifi_ip:
                print(f"WiFi sudah ada dari sebelumnya: {wifi_ip}")
        except Exception:
            wifi_ip = ""
else:
    print("AURAL_WIFI_SSID kosong — lewati connect dari script (pakai Settings atau set env).")
    try:
        wifi_ip = (w.get_ip() or "").strip()
        wifi_connected = bool(wifi_ip)
    except Exception:
        wifi_ip = ""

# ============================================================
# WARNA
# ============================================================
C_BG      = image.Color.from_rgb(12,  12,  22)
C_WHITE   = image.Color.from_rgb(255, 255, 255)
C_GRAY    = image.Color.from_rgb(100, 100, 120)
C_DKGRAY  = image.Color.from_rgb(28,  28,  42)
C_BLACK   = image.Color.from_rgb(0,   0,   0)
C_RED     = image.Color.from_rgb(220, 50,  50)
C_GREEN   = image.Color.from_rgb(50,  200, 80)
C_BLUE    = image.Color.from_rgb(40,  120, 255)
C_PURPLE  = image.Color.from_rgb(150, 60,  220)
C_YELLOW  = image.Color.from_rgb(240, 190, 0)
C_CYAN    = image.Color.from_rgb(0,   200, 210)

# ============================================================
# STATE GLOBAL
# ============================================================
current_mode     = MODE_MENU
processing       = False
last_result_text = ""
last_post_time   = 0.0
last_heartbeat   = 0.0
last_preview_ts  = 0.0
pressed_already  = False

# ============================================================
# HELPER: Koordinat layar ↔ kamera
# ============================================================
def scr_to_cam(sx, sy):
    """Konversi koordinat touchscreen (layar) ke koordinat gambar kamera."""
    cx = int((sx - CAM_OFF_X) / CAM_SCALE)
    cy = int((sy - CAM_OFF_Y) / CAM_SCALE)
    return cx, cy

def get_nav_tap(tx, ty):
    """
    Jika tap berada di area nav bar bawah, kembalikan mode yang ditap.
    Kembalikan None jika bukan di nav bar.
    """
    if ty < NAV_SCR_Y:
        return None
    btn_idx = (tx - CAM_OFF_X) // NAV_BTN_W
    modes = [MODE_OBJECT, MODE_TEXT, MODE_SCENE]
    if 0 <= btn_idx < 3:
        return modes[btn_idx]
    return None

def is_back_tap(tx, ty):
    """Tap di area header kiri atas = kembali ke menu."""
    return ty < HDR_SCR_Y and tx < int(90 * CAM_SCALE)

# ============================================================
# HELPER: Gambar UI di atas frame kamera
# ============================================================
def draw_header(img, mode_name, right=""):
    """Bar atas: nama mode + teks status kanan."""
    img.draw_rect(0, 0, CAM_W, 22, C_DKGRAY, thickness=-1)
    img.draw_string(3, 4, f"< Menu | {mode_name}", C_WHITE, scale=1)
    if right:
        rx = max(CAM_W - len(right) * 7 - 4, CAM_W // 2 + 10)
        img.draw_string(rx, 4, right, C_YELLOW, scale=1)

def draw_nav_bar(img, active_mode):
    """
    Bar navigasi bawah dengan 3 tombol mode.
    Mode aktif ditampilkan dengan warna penuh.
    """
    btn_w  = CAM_W // 3
    labels = ["Auto", "OCR", "Desc"]
    colors = [C_BLUE, C_GREEN, C_PURPLE]
    modes  = [MODE_OBJECT, MODE_TEXT, MODE_SCENE]

    for i in range(3):
        bx     = i * btn_w
        active = (active_mode == modes[i])
        bg     = colors[i] if active else C_DKGRAY
        img.draw_rect(bx, CAM_H - NAV_H, btn_w, NAV_H, bg, thickness=-1)
        if not active:
            img.draw_rect(bx, CAM_H - NAV_H, btn_w, NAV_H, colors[i], thickness=1)
        # Label di tengah tombol
        lbl_x = bx + max(btn_w // 2 - len(labels[i]) * 4, 5)
        img.draw_string(lbl_x, CAM_H - NAV_H + 4, labels[i], C_WHITE, scale=1)
        # Garis pemisah
        if i > 0:
            img.draw_line(bx, CAM_H - NAV_H, bx, CAM_H, C_GRAY, thickness=1)

def draw_menu_overlay(img):
    """
    Overlay menu di atas frame kamera.
    Menampilkan 3 tombol mode + nav bar.
    """
    # Header / judul
    img.draw_rect(0, 0, CAM_W, 28, C_DKGRAY, thickness=-1)
    img.draw_string(CAM_W // 2 - 36, 6, "AURALAI", C_CYAN, scale=1.5)
    wifi_txt = wifi_ip if wifi_connected else "OFFLINE"
    wifi_col = C_GREEN if wifi_connected else C_RED
    img.draw_string(CAM_W - 95, 9, wifi_txt, wifi_col, scale=1)

    # 3 tombol mode (camera y: 30–200)
    bw = CAM_W - 16
    bx = 8
    btn_data = [
        (30,  78,  C_BLUE,   "1. Deteksi Objek",   "Otomatis & terus-menerus"),
        (82,  130, C_GREEN,  "2. Baca Teks (OCR)",  "Ketuk layar untuk scan"),
        (134, 182, C_PURPLE, "3. Deskripsi Adegan", "Ketuk layar untuk deskripsi"),
    ]
    for (y1, y2, col, label, sublabel) in btn_data:
        bh = y2 - y1
        img.draw_rect(bx, y1, bw, bh, C_DKGRAY, thickness=-1)   # latar gelap
        img.draw_rect(bx, y1, bw, bh, col,      thickness=2)    # border berwarna
        img.draw_string(bx + 8, y1 + 7,  label,    col,    scale=1)
        img.draw_string(bx + 8, y1 + 25, sublabel, C_GRAY, scale=1)
    if not detector_ready:
        img.draw_string(bx + 8, 72, "! Model YOLOv5 tidak ada", C_RED, scale=1)

    # Nav bar bawah (bisa langsung tap ke mode)
    draw_nav_bar(img, MODE_MENU)

def draw_bottom(img, text, color=None):
    """Bar status bawah (di atas nav bar)."""
    if color is None:
        color = C_GRAY
    y = CAM_H - NAV_H - 17
    img.draw_rect(0, y, CAM_W, 17, C_DKGRAY, thickness=-1)
    img.draw_string(5, y + 2, text, color, scale=1)

def wrap_text(text, max_chars=38):
    lines = []
    while len(text) > max_chars:
        cut = text[:max_chars].rfind(" ")
        if cut < 5:
            cut = max_chars
        lines.append(text[:cut])
        text = text[cut:].strip()
    if text:
        lines.append(text)
    return lines

# ============================================================
# BACKGROUND THREAD: Kirim frame ke server AI
# ============================================================
def _send_frame_worker(task: str):
    global processing, last_result_text
    processing = True
    last_result_text = ""
    try:
        with open("/tmp/aural_cap.jpg", "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        payload = {"image": b64, "task": task}
        resp = requests.post(API_FRAME, json=payload, timeout=25)
        data = resp.json()
        last_result_text = data.get("result", "Tidak ada hasil")[:150]
    except Exception as e:
        err = str(e)
        print(f"Frame send GAGAL ({type(e).__name__}): {err}")  # log lengkap ke console
        last_result_text = f"Gagal: {err[:80]}"
    finally:
        processing = False

def capture_and_send(img_to_save, task: str):
    try:
        img_to_save.save("/tmp/aural_cap.jpg")
    except Exception as e:
        print(f"Gagal simpan capture: {e}")
        return
    t = threading.Thread(target=_send_frame_worker, args=(task,), daemon=True)
    t.start()

def _send_preview_worker():
    """Kirim preview frame ke server untuk MJPEG stream di browser."""
    try:
        with open("/tmp/aural_preview.jpg", "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        requests.post(API_PREVIEW, json={"image": b64}, timeout=0.5)
    except Exception:
        pass

def send_preview_async(img):
    """Simpan frame preview lalu kirim di background (max 2fps)."""
    global last_preview_ts
    now = time.time()
    if now - last_preview_ts < 0.5:
        return
    last_preview_ts = now
    try:
        img.save("/tmp/aural_preview.jpg")
    except Exception:
        return
    t = threading.Thread(target=_send_preview_worker, daemon=True)
    t.start()

def notify_mode(mode_id: int):
    if not wifi_connected or requests is None:
        return
    try:
        name = MODE_LABELS.get(mode_id, "")
        requests.post(API_MODE, json={"mode": mode_id, "name": name}, timeout=2)
    except Exception:
        pass

def switch_mode(new_mode: int):
    """Ganti mode, reset state, dan beritahu server."""
    global current_mode, last_result_text
    current_mode     = new_mode
    last_result_text = ""
    notify_mode(new_mode)

# ============================================================
# MAIN LOOP
# ============================================================
while not app.need_exit():
    img = cam.read()
    if img is None:
        time.sleep(0.05)
        continue

    # — Touchscreen —
    tx, ty, t_pressed = ts.read()
    clicked = False
    if t_pressed:
        pressed_already = True
    elif pressed_already:
        clicked = True
        pressed_already = False

    # — Heartbeat tiap 5 detik (semua mode) —
    now = time.time()
    if wifi_connected and requests and (now - last_heartbeat) > 5.0:
        last_heartbeat = now   # update dulu agar tidak spam jika gagal
        try:
            r = requests.post(
                API_PING,
                json={"mode": current_mode, "mode_name": MODE_LABELS.get(current_mode, "")},
                timeout=3.0,
            )
            try:
                _apply_ping_settings(r.json())
            except Exception:
                pass
            print(f"Heartbeat OK: {r.status_code}")
        except Exception as e:
            print(f"Heartbeat GAGAL: {e}")

    # ──────────────────────────────────────────────────────
    # MODE: MENU  (kamera sebagai background)
    # ──────────────────────────────────────────────────────
    if current_mode == MODE_MENU:
        frame = img.copy()
        draw_menu_overlay(frame)
        disp.show(frame)
        if wifi_connected:
            send_preview_async(frame)

        if clicked:
            nav = get_nav_tap(tx, ty)
            if nav is not None:
                switch_mode(nav)
            else:
                # Tombol besar di body — konversi ke koordinat kamera
                cx, cy = scr_to_cam(tx, ty)
                if 8 < cx < CAM_W - 8:
                    if 30 < cy < 78:
                        switch_mode(MODE_OBJECT)
                    elif 82 < cy < 130:
                        switch_mode(MODE_TEXT)
                    elif 134 < cy < 182:
                        switch_mode(MODE_SCENE)

    # ──────────────────────────────────────────────────────
    # MODE 1: DETEKSI OBJEK
    # ──────────────────────────────────────────────────────
    elif current_mode == MODE_OBJECT:
        payload = {
            "mode": "object",
            "camera": {"is_blur": False, "blur_score": 0.0},
            "objects": []
        }

        is_blur = False
        if CV2_AVAILABLE:
            try:
                img_cv     = image.image2cv(img, ensure_bgr=False, copy=False)
                gray       = cv2.cvtColor(img_cv, cv2.COLOR_RGB2GRAY)
                blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
                is_blur    = blur_score < float(_remote_cal.get("blur_threshold", BLUR_THRESHOLD))
                payload["camera"] = {"blur_score": round(blur_score, 2), "is_blur": is_blur}
            except Exception:
                pass

        if is_blur:
            img.draw_string(10, 40, "KAMERA BURAM!", C_RED, scale=2)
        elif detector_ready and detector is not None:
            try:
                cth = float(_remote_cal.get("conf_threshold", 0.5))
                ith = float(_remote_cal.get("iou_threshold", 0.45))
                objs = detector.detect(img, conf_th=cth, iou_th=ith)
                ign = _remote_cal.get("ignored_labels") or set()
                allow = _remote_cal.get("detection_allowlist") or []
                use_allow = bool(_remote_cal.get("use_detection_allowlist")) and len(allow) > 0
                allow_set = set(x.lower() for x in allow) if use_allow else None
                exm = _remote_cal.get("proximity_exempt_labels") or set()
                prox_on = bool(_remote_cal.get("proximity_alerts", True))
                ratio_th = float(_remote_cal.get("proximity_area_ratio", 0.82))

                for obj in objs:
                    label = (detector.labels[obj.class_id] or "").strip()
                    lab_l = label.lower()
                    if lab_l in ign:
                        continue
                    if allow_set is not None and lab_l not in allow_set:
                        continue

                    cx_obj = obj.x + obj.w / 2
                    pos    = "tengah"
                    if cx_obj < CAM_W / 3:      pos = "kiri"
                    elif cx_obj > CAM_W * 2 / 3: pos = "kanan"

                    ratio = (obj.w * obj.h) / (CAM_W * CAM_H)
                    warning = "aman"
                    if prox_on and lab_l not in exm and ratio > ratio_th:
                        warning = "terlalu dekat"

                    payload["objects"].append({
                        "label": label,
                        "score": round(obj.score, 2),
                        "position": pos,
                        "warning": warning,
                        "area_ratio": round(ratio, 4),
                    })
                    col = C_RED if warning == "terlalu dekat" else C_GREEN
                    img.draw_rect(obj.x, obj.y, obj.w, obj.h, col, thickness=2)
                    img.draw_string(obj.x, max(0, obj.y - 16), label, col, scale=1)
            except Exception:
                pass
        else:
            img.draw_string(10, 40, "Model tidak dimuat", C_YELLOW, scale=1)

        draw_header(img, "Deteksi Objek", "LIVE")
        net_txt = "ONLINE" if wifi_connected else "OFFLINE"
        draw_bottom(img, net_txt, C_GREEN if wifi_connected else C_RED)
        draw_nav_bar(img, MODE_OBJECT)

        if clicked:
            nav = get_nav_tap(tx, ty)
            if nav is not None and nav != MODE_OBJECT:
                switch_mode(nav)
            elif is_back_tap(tx, ty):
                switch_mode(MODE_MENU)

        if wifi_connected and requests and (now - last_post_time) > 0.35:
            try:
                requests.post(API_UPDATE, json=payload, timeout=0.2)
                last_post_time = now
            except Exception:
                pass

        disp.show(img)
        if wifi_connected:
            send_preview_async(img)

    # ──────────────────────────────────────────────────────
    # MODE 2 & 3: BACA TEKS / DESKRIPSI ADEGAN
    # ──────────────────────────────────────────────────────
    elif current_mode in (MODE_TEXT, MODE_SCENE):
        task_id    = "ocr" if current_mode == MODE_TEXT else "describe"
        mode_label = MODE_LABELS[current_mode]
        result_col = C_GREEN if current_mode == MODE_TEXT else C_PURPLE

        draw_header(img, mode_label, "PROSES..." if processing else "")

        if processing:
            img.draw_rect(0, CAM_H // 2 - 28, CAM_W, 56, C_DKGRAY, thickness=-1)
            img.draw_string(CAM_W // 2 - 54, CAM_H // 2 - 16,
                            "Memproses dengan AI...", C_YELLOW, scale=1)
            img.draw_string(CAM_W // 2 - 30, CAM_H // 2 + 4,
                            "Mohon tunggu", C_GRAY, scale=1)

        elif last_result_text:
            body_h = CAM_H - NAV_H - 22 - 36   # area antara header dan nav bar
            img.draw_rect(0, 24, CAM_W, body_h, C_DKGRAY, thickness=-1)
            img.draw_string(5, 27, "Hasil:", result_col, scale=1)
            lines = wrap_text(last_result_text, max_chars=38)
            for i, line in enumerate(lines[:5]):
                img.draw_string(5, 45 + i * 17, line, C_WHITE, scale=1)
            img.draw_string(5, CAM_H - NAV_H - 32, "Ketuk lagi untuk scan baru", C_GRAY, scale=1)

        else:
            hint1 = "Arahkan kamera ke teks" if current_mode == MODE_TEXT \
                    else "Arahkan ke lingkungan/objek"
            hint2 = "Ketuk layar untuk scan" if current_mode == MODE_TEXT \
                    else "Ketuk layar untuk deskripsi"
            mid_y = (CAM_H - NAV_H) // 2
            img.draw_string(CAM_W // 2 - 70, mid_y - 16, hint1, C_WHITE, scale=1)
            img.draw_string(CAM_W // 2 - 60, mid_y + 4,  hint2, C_YELLOW, scale=1)

        if not wifi_connected:
            draw_bottom(img, "WiFi OFFLINE — mode ini butuh internet", C_RED)
        else:
            draw_bottom(img, f"WiFi: {wifi_ip}", C_GREEN)

        draw_nav_bar(img, current_mode)

        if clicked:
            nav = get_nav_tap(tx, ty)
            if nav is not None and nav != current_mode:
                switch_mode(nav)
            elif is_back_tap(tx, ty):
                switch_mode(MODE_MENU)
            elif not processing and ty < NAV_SCR_Y and ty > HDR_SCR_Y:
                # Tap di body = aksi scan/deskripsi
                if not wifi_connected or requests is None:
                    last_result_text = "WiFi tidak terhubung. Hubungkan ke WiFi dulu."
                else:
                    fresh = cam.read()
                    capture_and_send(fresh if fresh else img, task_id)

        disp.show(img)
        if wifi_connected:
            send_preview_async(img)

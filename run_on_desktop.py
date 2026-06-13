"""
Sonara Desktop Runner — Web-Controlled
=======================================
Jalankan script ini, browser akan terbuka otomatis ke dashboard.
Kontrol mode & scan langsung dari browser, tidak perlu window terpisah.

Kebutuhan:
  pip install opencv-python requests

Opsional (deteksi YOLO lokal di Mode Auto):
  pip install ultralytics
"""
import cv2
import numpy as np
import requests
import threading
import base64
import time
import webbrowser
import sys

# ============================================================
# KONFIGURASI
# ============================================================
HOST_IP   = "127.0.0.1"
HOST_PORT = 5000

API_UPDATE       = f"http://{HOST_IP}:{HOST_PORT}/api/update"
API_FRAME        = f"http://{HOST_IP}:{HOST_PORT}/api/frame"
API_MODE         = f"http://{HOST_IP}:{HOST_PORT}/api/mode"
API_PING         = f"http://{HOST_IP}:{HOST_PORT}/api/ping"
API_PREVIEW      = f"http://{HOST_IP}:{HOST_PORT}/api/frame_preview"
API_CMD          = f"http://{HOST_IP}:{HOST_PORT}/api/command"
API_SETTINGS     = f"http://{HOST_IP}:{HOST_PORT}/api/settings"
API_MODEL_STATUS = f"http://{HOST_IP}:{HOST_PORT}/api/model_status"

CAM_W, CAM_H     = 320, 224
NAV_H            = 22
HEADER_H         = 22
BLUR_THRESHOLD   = 50.0
AREA_TOO_CLOSE   = 0.5

MODE_MENU   = 0
MODE_OBJECT = 1
MODE_TEXT   = 2
MODE_SCENE  = 3
MODE_LABELS = {0:"Menu", 1:"Deteksi Objek", 2:"Baca Teks (OCR)", 3:"Deskripsi Adegan"}

# ============================================================
# WARNA BGR
# ============================================================
def _rgb(r, g, b): return (b, g, r)

C_BG     = _rgb(12,  12,  22)
C_WHITE  = _rgb(255, 255, 255)
C_GRAY   = _rgb(120, 100, 100)
C_DKGRAY = _rgb(42,  28,  28)
C_RED    = _rgb(220, 50,  50)
C_GREEN  = _rgb(50,  200, 80)
C_BLUE   = _rgb(40,  120, 255)
C_PURPLE = _rgb(150, 60,  220)
C_YELLOW = _rgb(240, 190, 0)
C_CYAN   = _rgb(0,   200, 210)

FONT = cv2.FONT_HERSHEY_SIMPLEX

# ============================================================
# FUNGSI GAMBAR (seperti MaixPy, tapi cv2 BGR)
# ============================================================
def _pt(x, y): return (int(x), int(y))

def cv_text(img, x, y, text, color, scale=1):
    fs = max(0.28, 0.38 * scale)
    th = int(11 * scale)
    cv2.putText(img, str(text), _pt(x, y + th), FONT, fs, color, 1, cv2.LINE_AA)

def cv_fill(img, x, y, w, h, color):
    cv2.rectangle(img, _pt(x, y), _pt(x + w, y + h), color, -1)

def cv_rect(img, x, y, w, h, color, thickness=1):
    cv2.rectangle(img, _pt(x, y), _pt(x + w, y + h), color, thickness)

# ─── UI panels ───────────────────────────────────────────────
def draw_header(img, mode_name, right=""):
    cv_fill(img, 0, 0, CAM_W, HEADER_H, C_DKGRAY)
    cv_text(img, 3, 4, f"< Menu  |  {mode_name}", C_WHITE, scale=1)
    if right:
        rx = max(CAM_W - len(right) * 7 - 4, CAM_W // 2 + 10)
        cv_text(img, rx, 4, right, C_YELLOW, scale=1)

def draw_nav_bar(img, active_mode):
    btn_w  = CAM_W // 3
    labels = ["Auto", "OCR", "Desc"]
    colors = [C_BLUE, C_GREEN, C_PURPLE]
    modes  = [MODE_OBJECT, MODE_TEXT, MODE_SCENE]
    for i in range(3):
        bx     = i * btn_w
        active = (active_mode == modes[i])
        bg     = colors[i] if active else C_DKGRAY
        cv_fill(img, bx, CAM_H - NAV_H, btn_w, NAV_H, bg)
        if not active:
            cv_rect(img, bx, CAM_H - NAV_H, btn_w, NAV_H, colors[i], 1)
        lbl_x = bx + max(btn_w // 2 - len(labels[i]) * 4, 5)
        cv_text(img, lbl_x, CAM_H - NAV_H + 4, labels[i], C_WHITE, scale=1)
        if i > 0:
            cv2.line(img, _pt(bx, CAM_H - NAV_H), _pt(bx, CAM_H), C_GRAY, 1)

def draw_bottom(img, text, color=None):
    if color is None: color = C_GRAY
    y = CAM_H - NAV_H - 17
    cv_fill(img, 0, y, CAM_W, 17, C_DKGRAY)
    cv_text(img, 5, y + 2, text, color, scale=1)

def draw_menu_overlay(img):
    cv_fill(img, 0, 0, CAM_W, 28, C_DKGRAY)
    cv_text(img, CAM_W // 2 - 28, 6, "SONARA", C_CYAN, scale=1.5)
    cv_text(img, CAM_W - 95, 9, "Desktop Mode", C_GREEN, scale=1)
    entries = [
        (30,  78,  C_BLUE,   "1. Deteksi Objek",   "Otomatis & terus-menerus"),
        (82,  130, C_GREEN,  "2. Baca Teks (OCR)",  "Klik OCR di browser"),
        (134, 182, C_PURPLE, "3. Deskripsi Adegan", "Klik Desc di browser"),
    ]
    bw, bx = CAM_W - 16, 8
    for (y1, y2, col, label, sublbl) in entries:
        bh = y2 - y1
        cv_fill(img, bx, y1, bw, bh, C_DKGRAY)
        cv_rect(img, bx, y1, bw, bh, col, 2)
        cv_text(img, bx + 8, y1 + 7,  label, col,    scale=1)
        cv_text(img, bx + 8, y1 + 25, sublbl, C_GRAY, scale=1)
    draw_nav_bar(img, MODE_MENU)

def wrap_text(text, max_chars=38):
    lines, s = [], text
    while len(s) > max_chars:
        cut = s[:max_chars].rfind(" ")
        if cut < 5: cut = max_chars
        lines.append(s[:cut])
        s = s[cut:].strip()
    if s: lines.append(s)
    return lines

def render_maixcam_ui(frame_bgr):
    """Gambar UI MaixCam di atas frame — hasil dikirim ke server sebagai preview."""
    img = frame_bgr.copy()

    if current_mode == MODE_MENU:
        draw_menu_overlay(img)

    elif current_mode == MODE_OBJECT:
        infer_lbl = f"{_last_inference_ms}ms" if _last_inference_ms else "LIVE"
        draw_header(img, "Deteksi Objek", infer_lbl)
        if _last_detect_payload:
            objs = _last_detect_payload.get("objects", [])
            for i, o in enumerate(objs[:5]):
                danger = o.get("warning") == "terlalu dekat"
                col    = C_RED if danger else C_GREEN
                # Bounding box (hanya jika _show_bbox aktif)
                if _show_bbox:
                    bbox = o.get("bbox_norm")
                    if bbox:
                        bx1 = int(bbox[0] * CAM_W); by1 = int(bbox[1] * CAM_H)
                        bx2 = int(bbox[2] * CAM_W); by2 = int(bbox[3] * CAM_H)
                        cv_rect(img, bx1, by1, bx2 - bx1, by2 - by1, col, 2)
                        score_lbl = f"{o['label']} {int(o.get('score',0)*100)}%"
                        cv_text(img, bx1, max(0, by1 - 14), score_lbl, col, scale=1)
                else:
                    cv_text(img, 5, HEADER_H + 6 + i * 18,
                            f"  {o['label']} — {o['position']}", col, scale=1)
        draw_bottom(img, "Desktop Mode", C_CYAN)
        draw_nav_bar(img, MODE_OBJECT)

    elif current_mode in (MODE_TEXT, MODE_SCENE):
        mode_label = MODE_LABELS[current_mode]
        draw_header(img, mode_label, "PROSES..." if processing else "")
        mid_y = (CAM_H - NAV_H) // 2
        if processing:
            cv_fill(img, 0, mid_y - 20, CAM_W, 44, C_DKGRAY)
            cv_text(img, CAM_W // 2 - 54, mid_y - 12, "Memproses AI...", C_YELLOW, scale=1)
        elif last_result_text:
            body_y = HEADER_H + 4
            cv_fill(img, 0, body_y, CAM_W, CAM_H - NAV_H - body_y - 17, C_DKGRAY)
            col = C_GREEN if current_mode == MODE_TEXT else C_PURPLE
            cv_text(img, 5, body_y + 3, "Hasil:", col, scale=1)
            lines = wrap_text(last_result_text, max_chars=38)
            for i, line in enumerate(lines[:5]):
                cv_text(img, 5, body_y + 20 + i * 17, line, C_WHITE, scale=1)
        else:
            hint = ("Klik OCR di browser" if current_mode == MODE_TEXT
                    else "Klik Desc di browser")
            cv_text(img, CAM_W // 2 - 65, mid_y - 8,  "Arahkan kamera...", C_WHITE,  scale=1)
            cv_text(img, CAM_W // 2 - 60, mid_y + 10, hint,                C_YELLOW, scale=1)
        draw_bottom(img, "Desktop Mode", C_CYAN)
        draw_nav_bar(img, current_mode)

    return img

# ============================================================
# DETEKSI YOLO (opsional)
# ============================================================
YOLO_OK    = False
yolo_model = None
try:
    from ultralytics import YOLO
    yolo_model = YOLO("yolov8n.pt")
    YOLO_OK    = True
    print("[Sonara] YOLO berhasil dimuat (ultralytics yolov8n)")
except Exception:
    print("[Sonara] INFO: ultralytics tidak ada — Mode Auto berjalan tanpa deteksi lokal")
    print("         Pasang dengan:  pip install ultralytics")

# ============================================================
# PSUTIL (opsional — baterai & suhu)
# ============================================================
try:
    import psutil as _psutil
    PSUTIL_OK = True
except ImportError:
    _psutil   = None
    PSUTIL_OK = False
    print("[Sonara] INFO: psutil tidak ada — telemetry baterai/suhu tidak tersedia")
    print("         Pasang dengan:  pip install psutil")

# ============================================================
# STATE
# ============================================================
current_mode         = MODE_OBJECT
processing           = False
last_result_text     = ""
_last_detect_payload = None   # payload deteksi terakhir untuk ditampilkan di UI preview

# Tuning settings (di-sync dari server)
_conf_thresh = 0.45
_iou_thresh  = 0.45
_blur_thresh = 50.0

# Ping latency (ms) terakhir
_last_ping_ms      = None
_last_inference_ms = None   # YOLO inference time
_show_bbox         = True   # dari server settings

# ============================================================
# WEBCAM SETUP
# ============================================================
cap = cv2.VideoCapture(0)
if not cap.isOpened():
    print("[Sonara] WARN: Webcam tidak ditemukan — pakai frame hitam")

def read_frame():
    ret, frame = cap.read()
    if not ret or frame is None:
        return np.zeros((CAM_H, CAM_W, 3), dtype=np.uint8)
    return cv2.resize(frame, (CAM_W, CAM_H))

# ============================================================
# NETWORK HELPERS
# ============================================================
def _post(url, payload, timeout=2.0):
    try:
        requests.post(url, json=payload, timeout=timeout)
    except Exception:
        pass

def notify_mode(mode_id):
    _post(API_MODE, {"mode": mode_id, "name": MODE_LABELS.get(mode_id, "")})
    print(f"[Sonara] Mode -> {MODE_LABELS.get(mode_id, mode_id)}")

def _read_telemetry():
    """Baca baterai, WiFi, CPU, RAM, suhu dari sistem (pakai psutil jika ada)."""
    bat, wifi, temp, cpu_pct, ram_used, ram_total = None, None, None, None, None, None
    if PSUTIL_OK:
        try:
            b = _psutil.sensors_battery()
            if b: bat = round(b.percent)
        except Exception: pass
        try:
            cpu_pct = round(_psutil.cpu_percent(interval=None))
        except Exception: pass
        try:
            vm = _psutil.virtual_memory()
            ram_used  = round(vm.used  / 1024 / 1024)
            ram_total = round(vm.total / 1024 / 1024)
        except Exception: pass
        try:
            temps_dict = _psutil.sensors_temperatures()
            for _, entries in (temps_dict or {}).items():
                if entries:
                    temp = round(entries[0].current, 1)
                    break
        except Exception: pass
    return bat, wifi, temp, cpu_pct, ram_used, ram_total

def send_heartbeat():
    global _last_ping_ms, _show_bbox
    bat, wifi, temp, cpu_pct, ram_used, ram_total = _read_telemetry()
    payload = {
        "mode":         current_mode,
        "mode_name":    MODE_LABELS.get(current_mode, ""),
        "battery_pct":  bat,
        "wifi_dbm":     wifi,
        "cpu_temp_c":   temp,
        "cpu_pct":      cpu_pct,
        "ram_used_mb":  ram_used,
        "ram_total_mb": ram_total,
        "ping_ms":      _last_ping_ms,
        "inference_ms": _last_inference_ms,
    }
    t0 = time.time()
    try:
        r = requests.post(API_PING, json=payload, timeout=2)
        _last_ping_ms = round((time.time() - t0) * 1000, 1)
        print(f"[Sonara] Heartbeat OK: {r.status_code} ({_last_ping_ms}ms)")
        srv = r.json()
        if "settings" in srv:
            _apply_settings(srv["settings"])
            # Apply bbox toggle
            _show_bbox = bool(srv["settings"].get("show_bbox", True))
    except Exception as e:
        _last_ping_ms = None
        print(f"[Sonara] Heartbeat GAGAL: {e}")

def send_update(payload):
    _post(API_UPDATE, payload, timeout=0.3)

def _apply_settings(cfg):
    global _conf_thresh, _iou_thresh, _blur_thresh
    if "conf_threshold"  in cfg: _conf_thresh = float(cfg["conf_threshold"])
    if "iou_threshold"   in cfg: _iou_thresh  = float(cfg["iou_threshold"])
    if "blur_threshold"  in cfg: _blur_thresh  = float(cfg["blur_threshold"])

def _set_model_status(status, detail=""):
    _post(API_MODEL_STATUS, {"status": status, "detail": detail}, timeout=0.5)

def send_preview(frame_bgr):
    """Gambar UI MaixCam di atas frame, lalu kirim ke server untuk MJPEG stream."""
    try:
        ui_frame = render_maixcam_ui(frame_bgr)
        ok, buf  = cv2.imencode(".jpg", ui_frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if ok:
            b64 = base64.b64encode(buf).decode("utf-8")
            requests.post(API_PREVIEW, json={"image": b64}, timeout=0.5)
    except Exception:
        pass

# ─── AI Frame worker ─────────────────────────────────────────
def _frame_worker(frame_bgr, task):
    global processing, last_result_text
    processing = True
    last_result_text = ""
    _set_model_status("inferencing", task)
    try:
        ok, buf = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            raise RuntimeError("JPEG encode gagal")
        b64  = base64.b64encode(buf).decode("utf-8")
        resp = requests.post(API_FRAME, json={"image": b64, "task": task}, timeout=25)
        last_result_text = resp.json().get("result", "Tidak ada hasil")[:200]
        print(f"[Sonara] AI hasil: {last_result_text[:80]}")
    except Exception as e:
        print(f"[Sonara] Frame GAGAL: {e}")
        last_result_text = f"Gagal: {str(e)[:80]}"
    finally:
        processing = False
        _set_model_status("idle")

def trigger_scan(frame_bgr):
    if processing:
        print("[Sonara] Masih memproses, skip scan")
        return
    task = "ocr" if current_mode == MODE_TEXT else "describe"
    t = threading.Thread(target=_frame_worker, args=(frame_bgr.copy(), task), daemon=True)
    t.start()

# ─── Poll command dari server ────────────────────────────────
def poll_command():
    """Cek apakah ada perintah dari dashboard (mode change / scan trigger)."""
    global current_mode
    try:
        r = requests.get(API_CMD, timeout=0.4)
        cmd = r.json()
        ctype = cmd.get("type")
        if ctype == "set_mode":
            new_mode = int(cmd.get("mode", current_mode))
            if new_mode != current_mode:
                current_mode = new_mode
                notify_mode(current_mode)
        elif ctype == "scan":
            return "scan"
    except Exception:
        pass
    return None

# ============================================================
# THREAD: buka browser setelah delay
# ============================================================
def _open_browser():
    time.sleep(2.0)
    url = f"http://{HOST_IP}:{HOST_PORT}"
    print(f"[Sonara] Membuka browser: {url}")
    webbrowser.open(url)

threading.Thread(target=_open_browser, daemon=True).start()

# ============================================================
# MAIN LOOP
# ============================================================
print("\n" + "=" * 55)
print("  Sonara Desktop Runner")
print(f"  Server  : http://{HOST_IP}:{HOST_PORT}")
print(f"  Camera  : {'OK' if cap.isOpened() else 'TIDAK TERSEDIA'}")
print(f"  YOLO    : {'OK (yolov8n)' if YOLO_OK else 'Tidak terpasang'}")
print("  Kontrol : gunakan browser yang akan terbuka otomatis")
print("  Berhenti: Ctrl+C")
print("=" * 55 + "\n")

_last_heartbeat   = 0.0
_last_preview_ts  = 0.0
_last_update_ts   = 0.0
_last_cmd_poll_ts = 0.0

notify_mode(current_mode)

try:
    while True:
        now       = time.time()
        frame_bgr = read_frame()

        # ── Poll command (setiap 250ms) ──────────────────────
        if now - _last_cmd_poll_ts > 0.25:
            _last_cmd_poll_ts = now
            action = poll_command()
            if action == "scan" and current_mode in (MODE_TEXT, MODE_SCENE):
                trigger_scan(frame_bgr)

        # ── Heartbeat (setiap 5 detik) ──────────────────────
        if now - _last_heartbeat > 5.0:
            _last_heartbeat = now
            threading.Thread(target=send_heartbeat, daemon=True).start()

        # ── Preview ke server (max 4fps) ─────────────────────
        if now - _last_preview_ts > 0.25:
            _last_preview_ts = now
            threading.Thread(target=send_preview, args=(frame_bgr.copy(),), daemon=True).start()

        # ── Mode AUTO: deteksi objek (max ~3fps) ──────────────
        if current_mode == MODE_OBJECT and now - _last_update_ts > 0.35:
            _last_update_ts = now
            payload = {
                "mode": "object",
                "camera": {"is_blur": False, "blur_score": 0.0},
                "objects": [],
            }

            # Blur check (gunakan threshold dari settings)
            gray        = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
            blur_score  = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            payload["camera"] = {
                "blur_score": round(blur_score, 2),
                "is_blur"   : blur_score < _blur_thresh,
            }

            # YOLO detection (gunakan conf threshold dari settings)
            if YOLO_OK and yolo_model and not payload["camera"]["is_blur"]:
                _set_model_status("inferencing", "yolo")
                frame_rgb  = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
                t_infer    = time.time()
                results    = yolo_model(frame_rgb, verbose=False,
                                        conf=_conf_thresh, iou=_iou_thresh)
                _last_inference_ms = round((time.time() - t_infer) * 1000, 1)
                _set_model_status("idle")
                objs = []
                for r in results:
                    for box in r.boxes:
                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                        score  = float(box.conf[0])
                        cls    = int(box.cls[0])
                        label  = yolo_model.names[cls]
                        cx_obj = (x1 + x2) / 2
                        pos    = ("kiri"  if cx_obj < CAM_W / 3
                                  else "kanan" if cx_obj > CAM_W * 2 / 3
                                  else "tengah")
                        ratio   = ((x2 - x1) * (y2 - y1)) / (CAM_W * CAM_H)
                        warning = "terlalu dekat" if ratio > AREA_TOO_CLOSE else "aman"
                        objs.append({
                            "label":    label,
                            "score":    round(score, 2),
                            "position": pos,
                            "warning":  warning,
                            # bbox_norm untuk anotasi YOLO (0-1 normalized)
                            "bbox_norm": [
                                round(x1 / CAM_W, 6), round(y1 / CAM_H, 6),
                                round(x2 / CAM_W, 6), round(y2 / CAM_H, 6),
                            ],
                        })
                payload["objects"] = objs

            _last_detect_payload = payload
            threading.Thread(target=send_update, args=(payload,), daemon=True).start()

        time.sleep(0.04)   # ~25fps loop

except KeyboardInterrupt:
    print("\n[Sonara] Dihentikan.")
finally:
    cap.release()
    print("[Sonara] Selesai.")

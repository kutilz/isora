from flask import Flask, request, jsonify, render_template_string, Response
from openai import OpenAI
import threading
import time
import socket
import os
import base64
import json
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
HOST_PORT = 5000

try:
    client = OpenAI(api_key=os.getenv("SONARA_API_KEY"))
    openai_available = True
except Exception:
    openai_available = False

# ============================================================
# COMMAND STATE (dikirim dari browser → diambil oleh desktop runner)
# ============================================================
_cmd      = {"type": None, "mode": None}
_cmd_lock = threading.Lock()

# ============================================================
# TELEMETRY (dikirim device via /api/ping)
# ============================================================
_telemetry = {
    # Daya & jaringan
    "battery_pct":     None,   # int 0-100
    "wifi_dbm":        None,   # float dBm
    "ping_ms":         None,   # float ms (RTT terakhir)
    "cpu_temp_c":      None,   # float °C
    # AI performance
    "inference_ms":    None,   # YOLO/AI inference time per frame (ms)
    "kpu_fps":         None,   # FPS NPU (dihitung dari inference_ms)
    "display_fps":     None,   # FPS stream preview
    # Edge device resources
    "cpu_pct":         None,   # CPU usage %
    "ram_used_mb":     None,   # RAM terpakai MB
    "ram_total_mb":    None,   # RAM total MB
    # Kualitas jaringan
    "jitter_ms":       None,   # std-dev inter-ping interval (ms)
    "packet_loss_pct": 0.0,    # % ping yang terlewat
}

# Jitter calculation state
_ping_recv_times: list = []   # timestamp ping diterima (20 terakhir)
_ping_interval_expected = 5.0 # heartbeat MaixCam/desktop: 5s

# ============================================================
# TUNING SETTINGS (sliders di dev panel)
# ============================================================
_settings = {
    "conf_threshold":  0.45,
    "iou_threshold":   0.45,
    "blur_threshold":  50.0,
    "show_bbox":       True,   # tampilkan bounding box di preview
}
_settings_lock = threading.Lock()

# ============================================================
# RAW PAYLOAD INSPECTOR
# ============================================================
_raw_payloads   = {"update": {}, "ping": {}}
_raw_lock       = threading.Lock()
_raw_update_ts  = 0.0   # kapan terakhir /api/update diterima

# ============================================================
# ALERT HISTORY (riwayat 20 peringatan terakhir)
# ============================================================
_alert_history      = []   # [{"ts": "HH:MM:SS", "text": str, "type": str}]
_alert_history_lock = threading.Lock()
MAX_ALERT_HIST      = 20

def _alert_hist_add(text: str, atype: str = "info"):
    ts = datetime.now().strftime("%H:%M:%S")
    with _alert_history_lock:
        _alert_history.append({"ts": ts, "text": text, "type": atype})
        if len(_alert_history) > MAX_ALERT_HIST:
            _alert_history.pop(0)

# ============================================================
# DEBUG LOG (50 baris terakhir)
# ============================================================
_debug_log      = []   # [{"ts": str, "msg": str}]
_debug_log_lock = threading.Lock()
MAX_DEBUG_LOG   = 50

def _dbg(msg: str):
    ts = datetime.now().strftime("%H:%M:%S.") + f"{datetime.now().microsecond // 1000:03d}"
    with _debug_log_lock:
        _debug_log.append({"ts": ts, "msg": msg})
        if len(_debug_log) > MAX_DEBUG_LOG:
            _debug_log.pop(0)

# ============================================================
# MODEL STATUS (idle | loading | inferencing)
# ============================================================
_model_status = {"status": "idle", "detail": ""}

# ============================================================
# CAPTURES (snapshot + metadata)
# ============================================================
CAPTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "captures")
os.makedirs(CAPTURE_DIR, exist_ok=True)

# ============================================================
# PREVIEW FRAME (untuk MJPEG stream ke browser)
# ============================================================
_preview_frame: bytes | None = None
_preview_lock  = threading.Lock()

# Placeholder JPEG (1×1 hitam) saat belum ada frame
_PLACEHOLDER_JPEG = (
    b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00'
    b'\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c'
    b'\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c'
    b'\x1c $.\' ",#\x1c\x1c(7),01444\x1f\'9=82<.342\x1edL\t\xff\xc0\x00\x0b\x08'
    b'\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01'
    b'\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04'
    b'\x05\x06\x07\x08\t\n\x0b\xff\xc4\x00\xb5\x10\x00\x02\x01\x03\x03\x02'
    b'\x04\x03\x05\x05\x04\x04\x00\x00\x01}\x01\x02\x03\x00\x04\x11\x05\x12'
    b'!1A\x06\x13Qa\x07"q\x142\x81\x91\xa1\x08#B\xb1\xc1\x15R\xd1\xf0$3br'
    b'\x82\t\n\x16\x17\x18\x19\x1a%&\'()*456789:CDEFGHIJSTUVWXYZcdefghij'
    b'stuvwxyz\x83\x84\x85\x86\x87\x88\x89\x8a\x92\x93\x94\x95\x96\x97\x98'
    b'\x99\x9a\xa2\xa3\xa4\xa5\xa6\xa7\xa8\xa9\xaa\xb2\xb3\xb4\xb5\xb6\xb7'
    b'\xb8\xb9\xba\xc2\xc3\xc4\xc5\xc6\xc7\xc8\xc9\xca\xd2\xd3\xd4\xd5\xd6'
    b'\xd7\xd8\xd9\xda\xe1\xe2\xe3\xe4\xe5\xe6\xe7\xe8\xe9\xea\xf1\xf2\xf3'
    b'\xf4\xf5\xf6\xf7\xf8\xf9\xfa\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xf5'
    b'\x07\xff\xd9'
)

# ============================================================
# STATE GLOBAL
# ============================================================
latest_data = {
    "camera":    {"is_blur": False, "blur_score": 0.0},
    "objects":   [],
    "last_update": 0,
    "mode":      1,
    "mode_name": "Deteksi Objek",
    "last_result": "",
}

current_speech_alert = ""
alert_source         = "lokal"
last_openai_trigger  = 0.0

# ============================================================
# SPEECH QUEUE — dipakai untuk notifikasi ke HP
# ============================================================
_sq_lock    = threading.Lock()
_sq_items   = []          # list of dict: {id, text, type, priority, ts}
_sq_counter = 0

def sq_add(text: str, stype: str = "info", priority: int = 1):
    global _sq_counter
    if not text:
        return
    with _sq_lock:
        _sq_counter += 1
        _sq_items.append({
            "id":       _sq_counter,
            "text":     text,
            "type":     stype,
            "priority": priority,
            "ts":       time.time(),
        })
        if len(_sq_items) > 200:
            _sq_items.pop(0)
    # Catat ke alert history dan debug log
    if stype in ("alert", "warning", "ocr", "describe", "system"):
        _alert_hist_add(text, stype)
    _dbg(f"[speech/{stype}] {text[:70]}")

# ============================================================
# FAIL-SAFE LOKAL (tanpa OpenAI)
# ============================================================
LABEL_ID = {
    "person":      "orang",     "chair":    "kursi",    "car":       "mobil",
    "bottle":      "botol",     "cell phone":"handphone","bed":       "kasur",
    "tv":          "televisi",  "dog":      "anjing",   "cat":       "kucing",
    "bicycle":     "sepeda",    "motorcycle":"motor",   "bus":       "bus",
    "truck":       "truk",      "table":    "meja",     "cup":       "cangkir",
    "laptop":      "laptop",    "door":     "pintu",    "stairs":    "tangga",
    "fire hydrant":"hidran",    "knife":    "pisau",    "scissors":  "gunting",
}

def failsafe_alert(objects: list) -> str:
    for o in objects:
        lbl = LABEL_ID.get(o["label"], o["label"])
        if o["warning"] == "terlalu dekat":
            return f"Awas! Ada {lbl} terlalu dekat di {o['position']}."
    if objects:
        lbl = LABEL_ID.get(objects[0]["label"], objects[0]["label"])
        return f"Ada {lbl} di {objects[0]['position']}."
    return ""

def _gen_alert_worker(objects: list):
    global current_speech_alert, alert_source, last_openai_trigger
    if not objects:
        current_speech_alert = ""
        return
    now = time.time()
    if (now - last_openai_trigger) < 2.5:
        return
    last_openai_trigger = now

    obj_str = ", ".join(
        f"{o['label']} ({o['position']}, {o['warning']})" for o in objects
    )
    prompt = (
        "Kamu adalah asisten kacamata tunanetra. Objek terdeteksi: "
        f"{obj_str}\n"
        "Buat 1 kalimat peringatan singkat dan natural dalam bahasa Indonesia. "
        "Prioritaskan objek 'terlalu dekat'. Maksimal 10 kata."
    )
    t0 = time.time()
    try:
        if not openai_available:
            raise RuntimeError("OpenAI tidak tersedia")
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=30,
            timeout=3.0,
        )
        current_speech_alert = resp.choices[0].message.content.replace('"', "").strip()
        alert_source = "openai"
        _dbg(f"[openai/alert] {round((time.time()-t0)*1000)}ms → {current_speech_alert[:50]}")
    except Exception as e:
        print(f"  OpenAI gagal → fail-safe: {e}")
        current_speech_alert = failsafe_alert(objects)
        alert_source = "lokal"
        _dbg(f"[openai/err] {str(e)[:60]} → failsafe")
    if current_speech_alert:
        _alert_hist_add(current_speech_alert, "warning")

# ============================================================
# ENDPOINTS API
# ============================================================

@app.route("/api/update", methods=["POST"])
def update_data():
    """Terima data dari MaixCam (mode deteksi objek)."""
    global latest_data, _raw_update_ts
    data = request.json
    if data:
        latest_data["camera"]      = data.get("camera", {"is_blur": False, "blur_score": 0.0})
        latest_data["objects"]     = data.get("objects", [])
        latest_data["last_update"] = time.time()
        # Simpan raw payload untuk JSON inspector
        with _raw_lock:
            _raw_payloads["update"] = data
            _raw_update_ts = time.time()
        if data.get("mode") == "object":
            threading.Thread(
                target=_gen_alert_worker,
                args=(latest_data["objects"],),
                daemon=True,
            ).start()
    return jsonify({"status": "ok"})


@app.route("/api/frame", methods=["POST"])
def process_frame():
    """
    Terima gambar base64 dari MaixCam, proses dengan GPT-4o vision.
    task = 'ocr'      → baca teks di gambar
    task = 'describe' → deskripsikan adegan
    """
    data     = request.json or {}
    task     = data.get("task", "describe")
    img_b64  = data.get("image", "")
    t0_frame = time.time()

    _model_status["status"] = "inferencing"
    _model_status["detail"] = task
    _dbg(f"[frame/{task}] received, processing...")
    latest_data["last_update"] = time.time()

    if not img_b64:
        _model_status["status"] = "idle"
        return jsonify({"result": "Tidak ada gambar diterima.", "status": "error"})

    prompts = {
        "ocr": (
            "Baca semua teks yang ada di gambar ini secara lengkap dan akurat. "
            "Jika tidak ada teks yang terbaca, jawab 'Tidak ada teks ditemukan'. "
            "Tulis hanya teks yang ada di gambar, tanpa komentar atau penjelasan tambahan."
        ),
        "describe": (
            "Kamu adalah asisten untuk penyandang tunanetra. "
            "Deskripsikan isi gambar ini dengan singkat dan jelas dalam bahasa Indonesia. "
            "Sebutkan objek utama, orang yang ada, dan potensi bahaya jika terlihat. "
            "Maksimal 2 kalimat pendek."
        ),
    }

    latest_data["last_update"] = time.time()  # tandai device online saat kirim frame
    result = ""
    try:
        if not openai_available:
            raise RuntimeError("OpenAI tidak tersedia")
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"},
                    },
                    {"type": "text", "text": prompts.get(task, prompts["describe"])},
                ],
            }],
            max_tokens=150,
            timeout=18,
        )
        result = resp.choices[0].message.content.strip()
        sq_add(result, stype=task, priority=5)
        _dbg(f"[openai/{task}] {round((time.time()-t0_frame)*1000)}ms OK")
    except Exception as e:
        result = f"Gagal memproses: {str(e)[:80]}"
        sq_add(result, stype="error", priority=5)
        _dbg(f"[openai/{task}] ERR: {str(e)[:60]}")

    _model_status["status"] = "idle"
    latest_data["last_result"] = result
    return jsonify({"result": result, "status": "ok"})


@app.route("/api/mode", methods=["POST"])
def mode_change():  # noqa: E302
    """Terima notifikasi pergantian mode dari MaixCam."""
    data     = request.json or {}
    mode_id  = data.get("mode", 1)
    name     = data.get("name", "")

    latest_data["mode"]        = mode_id
    latest_data["mode_name"]   = name
    latest_data["last_result"] = ""
    latest_data["last_update"] = time.time()
    _dbg(f"[mode] changed to {mode_id} ({name})")

    mode_msgs = {
        1: "Mode deteksi objek aktif.",
        2: "Mode baca teks aktif. Ketuk layar kacamata untuk scan.",
        3: "Mode deskripsi adegan aktif. Ketuk layar kacamata untuk deskripsi.",
    }
    if mode_id in mode_msgs:
        sq_add(mode_msgs[mode_id], stype="system", priority=10)

    return jsonify({"status": "ok"})


@app.route("/api/frame_preview", methods=["POST"])
def frame_preview():
    """Terima frame JPEG dari device untuk ditampilkan di MJPEG stream."""
    global _preview_frame
    data    = request.json or {}
    img_b64 = data.get("image", "")
    if img_b64:
        with _preview_lock:
            _preview_frame = base64.b64decode(img_b64)
    return jsonify({"status": "ok"})


def _mjpeg_generator():
    """Generator untuk MJPEG streaming ke browser."""
    while True:
        with _preview_lock:
            frame = _preview_frame or _PLACEHOLDER_JPEG
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
        )
        time.sleep(0.07)   # ~14 fps max


@app.route("/api/stream")
def video_stream():
    """MJPEG stream — bisa langsung dipakai sebagai src <img>."""
    return Response(
        _mjpeg_generator(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.route("/api/snapshot")
def snapshot():
    """Snapshot JPEG tunggal (fallback untuk browser yang tidak support MJPEG)."""
    with _preview_lock:
        frame = _preview_frame or _PLACEHOLDER_JPEG
    return Response(frame, mimetype="image/jpeg",
                    headers={"Cache-Control": "no-cache"})


@app.route("/api/command", methods=["GET", "POST"])
def command():
    """GET: ambil & hapus command pending (dipanggil desktop runner).
       POST: kirim command dari browser (set_mode / scan)."""
    global _cmd
    if request.method == "POST":
        data = request.json or {}
        with _cmd_lock:
            _cmd = {"type": data.get("type"), "mode": data.get("mode")}
        return jsonify({"status": "ok"})
    else:
        with _cmd_lock:
            snapshot = dict(_cmd)
            _cmd = {"type": None, "mode": None}
        return jsonify(snapshot)


@app.route("/api/ping", methods=["POST"])
def ping():
    """Heartbeat dari MaixCam — update timestamp, telemetry, dan hitung jitter."""
    data = request.json or {}
    now  = time.time()
    latest_data["last_update"] = now
    mode_id = data.get("mode", latest_data["mode"])
    name    = data.get("mode_name", latest_data["mode_name"])
    if mode_id is not None:
        latest_data["mode"]      = mode_id
        latest_data["mode_name"] = name

    # ── Semua field telemetry ──────────────────────────────
    for key in ("battery_pct", "wifi_dbm", "ping_ms", "cpu_temp_c",
                "inference_ms", "cpu_pct", "ram_used_mb", "ram_total_mb",
                "display_fps"):
        if data.get(key) is not None:
            _telemetry[key] = data[key]

    # KPU FPS dari inference_ms
    if _telemetry["inference_ms"]:
        _telemetry["kpu_fps"] = round(1000.0 / _telemetry["inference_ms"], 1)

    # ── Jitter & Packet Loss ───────────────────────────────
    _ping_recv_times.append(now)
    if len(_ping_recv_times) > 20:
        _ping_recv_times.pop(0)
    if len(_ping_recv_times) >= 3:
        intervals = [_ping_recv_times[i+1] - _ping_recv_times[i]
                     for i in range(len(_ping_recv_times) - 1)]
        mean_iv   = sum(intervals) / len(intervals)
        variance  = sum((x - mean_iv) ** 2 for x in intervals) / len(intervals)
        _telemetry["jitter_ms"] = round((variance ** 0.5) * 1000, 1)
        missed = sum(1 for iv in intervals if iv > _ping_interval_expected * 1.8)
        _telemetry["packet_loss_pct"] = round(missed / len(intervals) * 100, 1)

    # ── Raw payload inspector ──────────────────────────────
    with _raw_lock:
        _raw_payloads["ping"] = data

    # ── Model status ───────────────────────────────────────
    if data.get("model_status"):
        _model_status["status"] = data["model_status"]
        _model_status["detail"] = data.get("model_detail", "")

    _dbg(f"[ping] mode={mode_id} infer={_telemetry['inference_ms']}ms "
         f"cpu={_telemetry['cpu_pct']}% ram={_telemetry['ram_used_mb']}MB "
         f"jitter={_telemetry['jitter_ms']}ms")
    with _settings_lock:
        return jsonify({"status": "ok", "settings": _settings})


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    """GET: kembalikan settings saat ini. POST: update dari browser."""
    global _settings
    if request.method == "POST":
        data = request.json or {}
        with _settings_lock:
            for key in ("conf_threshold", "iou_threshold", "blur_threshold"):
                if key in data:
                    _settings[key] = round(float(data[key]), 3)
        _dbg(f"[settings] updated: {_settings}")
        return jsonify({"status": "ok", "settings": _settings})
    with _settings_lock:
        return jsonify(_settings)


@app.route("/api/model_status", methods=["POST"])
def api_model_status():
    """Update status model dari device (idle / loading / inferencing)."""
    data = request.json or {}
    _model_status["status"] = data.get("status", "idle")
    _model_status["detail"] = data.get("detail", "")
    _dbg(f"[model] {_model_status['status']} — {_model_status['detail']}")
    return jsonify({"status": "ok"})


@app.route("/api/capture", methods=["POST"])
def api_capture():
    """Simpan frame saat ini + metadata JSON + anotasi YOLO .txt ke folder captures/."""
    with _preview_lock:
        frame = _preview_frame
    if not frame:
        return jsonify({"status": "error", "message": "Tidak ada frame tersedia"}), 400

    ts      = datetime.now().strftime("%Y%m%d_%H%M%S")
    flagged = (request.json or {}).get("flagged", False)
    objs    = latest_data.get("objects", [])

    # Simpan JPEG
    img_path = os.path.join(CAPTURE_DIR, f"cap_{ts}.jpg")
    with open(img_path, "wb") as f:
        f.write(frame)

    # Simpan metadata JSON
    meta = {
        "timestamp": ts, "flagged": flagged,
        "mode": latest_data.get("mode"),
        "mode_name": latest_data.get("mode_name"),
        "objects": objs,
        "blur_score": latest_data.get("camera", {}).get("blur_score", 0),
        "telemetry": dict(_telemetry),
    }
    with open(os.path.join(CAPTURE_DIR, f"cap_{ts}.json"), "w") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    # Simpan anotasi YOLO .txt (jika objek punya bbox_norm)
    yolo_lines = []
    all_labels = []
    for obj in objs:
        bbox = obj.get("bbox_norm")   # [x1_n, y1_n, x2_n, y2_n] normalized 0-1
        label = obj.get("label", "unknown")
        if label not in all_labels:
            all_labels.append(label)
        cls_id = all_labels.index(label)
        if bbox and len(bbox) == 4:
            x1n, y1n, x2n, y2n = bbox
            cx = (x1n + x2n) / 2
            cy = (y1n + y2n) / 2
            bw = x2n - x1n
            bh = y2n - y1n
            yolo_lines.append(f"{cls_id} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")

    if yolo_lines:
        with open(os.path.join(CAPTURE_DIR, f"cap_{ts}.txt"), "w") as f:
            f.write("\n".join(yolo_lines))
        # Update labels.txt global
        labels_path = os.path.join(CAPTURE_DIR, "labels.txt")
        existing = []
        if os.path.exists(labels_path):
            with open(labels_path) as f:
                existing = [l.strip() for l in f.readlines()]
        for lbl in all_labels:
            if lbl not in existing:
                existing.append(lbl)
        with open(labels_path, "w") as f:
            f.write("\n".join(existing))

    saved_types = ["jpg", "json"] + (["txt (YOLO)"] if yolo_lines else [])
    _dbg(f"[capture] {'FLAG' if flagged else 'snap'}: cap_{ts} — {', '.join(saved_types)}")
    print(f"[Sonara] Capture: {img_path} | YOLO annotations: {len(yolo_lines)} objs")
    return jsonify({"status": "ok", "file": f"cap_{ts}.jpg",
                    "annotations": len(yolo_lines), "flagged": flagged})


@app.route("/api/latest_payload", methods=["GET"])
def api_latest_payload():
    """Kembalikan payload mentah terakhir dari /api/update dan /api/ping."""
    with _raw_lock:
        return jsonify({
            "update": _raw_payloads["update"],
            "ping":   _raw_payloads["ping"],
            "update_age_s": round(time.time() - _raw_update_ts, 1) if _raw_update_ts else None,
        })


@app.route("/api/debug_log", methods=["GET"])
def api_debug_log():
    """Kembalikan 50 debug log entries terakhir."""
    since = request.args.get("since", 0, type=int)
    with _debug_log_lock:
        entries = list(_debug_log[since:])
    return jsonify({"entries": entries, "total": len(_debug_log)})


@app.route("/api/status", methods=["GET"])
def get_status():
    is_online = (time.time() - latest_data["last_update"]) < 6.0
    with _alert_history_lock:
        hist = list(reversed(_alert_history))  # newest first
    with _settings_lock:
        cfg = dict(_settings)
    return jsonify({
        **latest_data,
        "is_online":     is_online,
        "speech_alert":  current_speech_alert,
        "alert_source":  alert_source,
        "telemetry":     dict(_telemetry),
        "alert_history": hist,
        "settings":      cfg,
        "model_status":  dict(_model_status),
        "captures_dir":  CAPTURE_DIR,
    })


@app.route("/api/speech_poll", methods=["GET"])
def speech_poll():
    """HP polling untuk item speech queue baru."""
    since_id = request.args.get("since_id", 0, type=int)
    with _sq_lock:
        items  = [i for i in _sq_items if i["id"] > since_id]
        cutoff = time.time() - 300
        _sq_items[:] = [i for i in _sq_items if i["ts"] > cutoff]
    return jsonify({"items": items})


# ============================================================
# WEB DASHBOARD (dibuka di HP / browser)
# ============================================================
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="id">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>Sonara</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    body { -webkit-tap-highlight-color: transparent; }
    .pulse  { animation: pulse  1.5s ease-in-out infinite; }
    .spin   { animation: spin   1s   linear    infinite; }
    @keyframes pulse { 0%,100%{opacity:1}  50%{opacity:.3} }
    @keyframes spin  { to{transform:rotate(360deg)} }
    .btn-tap:active { transform: scale(.95); }
    #cam-img { image-rendering: pixelated; }
    #cam-wrap::after {
      content:""; position:absolute; inset:0; pointer-events:none;
      background: repeating-linear-gradient(to bottom,transparent 0px,transparent 3px,rgba(0,0,0,.06) 3px,rgba(0,0,0,.06) 4px);
      border-radius: inherit;
    }
    /* Alert history scroll */
    #alert-history::-webkit-scrollbar { width: 3px; }
    #alert-history::-webkit-scrollbar-thumb { background: #374151; border-radius:2px; }
    /* Debug console scroll */
    #debug-console::-webkit-scrollbar { width:3px; }
    #debug-console::-webkit-scrollbar-thumb { background:#1f2937; border-radius:2px; }
    /* Range sliders */
    input[type=range] { accent-color: #3b82f6; }
    /* Collapsible dev panel */
    details > summary { cursor: pointer; list-style: none; }
    details > summary::-webkit-details-marker { display: none; }
    details[open] > summary .chevron { transform: rotate(90deg); }
    .chevron { transition: transform .2s; display:inline-block; }
    /* Thermal warning banner */
    #thermal-banner { display:none; }
    #thermal-banner.show { display:flex; }
  </style>
</head>
<body class="bg-gray-950 text-white font-sans min-h-screen pb-8 select-none">

<!-- ===== OVERLAY AKTIFKAN AUDIO ===== -->
<div id="overlay" class="fixed inset-0 bg-gray-950/95 z-50 flex items-center justify-center p-6 backdrop-blur-sm">
  <div class="bg-gray-900 border border-gray-800 rounded-3xl p-8 max-w-sm w-full text-center shadow-2xl">
    <div class="text-5xl mb-5">&#128374;</div>
    <h1 class="text-3xl font-black text-blue-400 mb-1 tracking-wide">SONARA</h1>
    <p class="text-gray-500 text-sm mb-1">Kacamata Pintar Tunanetra</p>
    <p class="text-gray-600 text-xs mb-8">Ketuk tombol untuk mengaktifkan audio &amp; monitoring</p>
    <button onclick="startApp()"
      class="w-full bg-blue-600 hover:bg-blue-500 active:bg-blue-700 text-white font-bold py-4 rounded-2xl text-lg shadow-lg shadow-blue-900/40 transition btn-tap">
      &#9654;&nbsp; Mulai Sonara
    </button>
  </div>
</div>

<!-- ===== MAIN LAYOUT ===== -->
<div class="max-w-5xl mx-auto p-4 pt-5">

  <!-- ─── Thermal warning banner ─── -->
  <div id="thermal-banner" class="thermal-banner mb-3 bg-red-950/60 border border-red-700/60 rounded-xl px-4 py-2.5 items-center gap-3">
    <span class="text-xl">&#127777;&#65039;</span>
    <div>
      <p class="font-bold text-red-400 text-sm">Peringatan Suhu Tinggi</p>
      <p id="thermal-detail" class="text-xs text-red-300/60">SoC mendekati batas throttling — performa mungkin turun</p>
    </div>
  </div>

  <!-- ─── Header bar ─── -->
  <div class="flex items-center justify-between mb-4 gap-2 flex-wrap">
    <div>
      <h1 class="text-2xl font-black text-blue-400 tracking-widest">SONARA</h1>
      <p class="text-gray-600 text-[10px] tracking-widest uppercase">Observer Panel</p>
    </div>
    <div class="flex items-center gap-2 flex-wrap justify-end">
      <!-- Mode badge -->
      <div class="hidden sm:flex items-center gap-2 bg-gray-900 border border-gray-800 px-3 py-2 rounded-xl">
        <span id="mode-icon" class="text-lg">&#128269;</span>
        <div>
          <div class="text-[9px] text-gray-500 uppercase">Mode</div>
          <div id="mode-name" class="text-xs font-bold text-white leading-tight">Menunggu...</div>
        </div>
        <span id="mode-badge" class="px-2 py-0.5 bg-blue-900/30 text-blue-300 text-[10px] rounded-lg font-mono border border-blue-800">—</span>
      </div>
      <!-- Telemetry compact -->
      <div class="flex items-center gap-1.5 bg-gray-900 border border-gray-800 px-2.5 py-1.5 rounded-xl">
        <span id="tl-bat-icon" class="text-sm">&#128267;</span>
        <span id="tl-bat"   class="text-[11px] font-mono text-gray-400">—%</span>
        <span class="text-gray-700">|</span>
        <span id="tl-ping"  class="text-[11px] font-mono text-gray-400">—ms</span>
        <span class="text-gray-700">|</span>
        <span id="tl-temp"  class="text-[11px] font-mono text-gray-400">—°C</span>
      </div>
      <!-- Online dot -->
      <div class="flex items-center gap-2 bg-gray-900 border border-gray-800 px-3 py-2 rounded-xl">
        <div id="status-dot" class="h-2.5 w-2.5 rounded-full bg-red-500"></div>
        <span id="status-text" class="text-xs font-bold text-red-400 tracking-wider">OFFLINE</span>
      </div>
    </div>
  </div>

  <!-- ─── Mode info (mobile only) ─── -->
  <div class="sm:hidden flex items-center gap-2 bg-gray-900 border border-gray-800 rounded-xl px-3 py-2 mb-3">
    <span id="mode-icon-m" class="text-lg">&#128269;</span>
    <div class="flex-1 min-w-0">
      <div class="text-[9px] text-gray-500 uppercase">Mode</div>
      <div id="mode-name-m" class="text-xs font-bold text-white truncate">Menunggu koneksi...</div>
    </div>
    <span id="mode-badge-m" class="px-2 py-0.5 bg-blue-900/30 text-blue-300 text-[10px] rounded-lg font-mono border border-blue-800 shrink-0">—</span>
  </div>

  <!-- ─── TWO-COLUMN GRID ─── -->
  <div class="grid grid-cols-1 lg:grid-cols-5 gap-4">

    <!-- LEFT: Camera stream -->
    <div class="lg:col-span-3 space-y-3">

      <!-- Camera panel -->
      <div class="bg-gray-900 border border-gray-800 rounded-2xl overflow-hidden">
        <div class="flex items-center justify-between px-3 py-2.5 border-b border-gray-800">
          <div>
            <span class="text-[10px] text-gray-500 uppercase tracking-wider font-semibold">Simulasi Layar MaixCam</span>
            <span class="text-[9px] text-gray-700 ml-1.5">320 &times; 224</span>
          </div>
          <div class="flex items-center gap-2">
            <button id="flag-btn" onclick="captureSnapshot(true)"
              class="px-2.5 py-1 bg-red-900/30 hover:bg-red-900/60 border border-red-800/60 text-red-400 text-[10px] font-semibold rounded-lg transition btn-tap"
              title="Flag frame ini sebagai error untuk retrain model">
              &#9873; Flag Error
            </button>
            <button id="snap-btn" onclick="captureSnapshot(false)"
              class="px-2.5 py-1 bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-300 text-[10px] font-semibold rounded-lg transition btn-tap"
              title="Simpan snapshot">
              &#128247; Snap
            </button>
            <div id="cam-dot" class="h-2 w-2 rounded-full bg-gray-700"></div>
            <span id="cam-label" class="text-[10px] text-gray-600 font-mono">no signal</span>
          </div>
        </div>
        <!-- MJPEG stream — aspect ratio 320:224 = 70% -->
        <div id="cam-wrap" class="relative bg-black" style="padding-bottom:70%">
          <img id="cam-img" class="absolute inset-0 w-full h-full object-contain"
               src="/api/stream"
               onerror="camError()"
               onload="camLoaded()"
               alt="camera feed">
          <!-- Overlay saat no-signal -->
          <div id="cam-nosignal" class="absolute inset-0 flex flex-col items-center justify-center bg-gray-950">
            <div class="text-4xl mb-3 text-gray-800">&#128247;</div>
            <p class="text-gray-700 text-sm font-mono">Menunggu stream...</p>
            <p class="text-gray-800 text-[10px] mt-1">Jalankan run_on_desktop.py atau run_on_maix.py</p>
          </div>
        </div>
      </div>

      <!-- Blur alert (di bawah camera) -->
      <div id="blur-alert" class="hidden bg-yellow-900/20 border border-yellow-700/40 rounded-2xl px-4 py-3 flex items-center gap-3">
        <span class="text-2xl">&#9888;&#65039;</span>
        <div>
          <p class="font-bold text-yellow-400 text-sm">Lensa Buram</p>
          <p class="text-xs text-yellow-200/50">Bersihkan lensa atau atur jarak kamera</p>
        </div>
      </div>

      <!-- Objects grid (Mode 1) -->
      <div id="objects-section">
        <p class="text-[10px] text-gray-600 uppercase tracking-wider mb-2 px-1">Objek Terdeteksi</p>
        <div id="objects-grid" class="grid grid-cols-2 sm:grid-cols-3 gap-2">
          <div class="col-span-2 sm:col-span-3 bg-gray-900 border border-gray-800 rounded-xl p-3 text-center text-gray-600 text-sm">
            Belum ada objek
          </div>
        </div>
      </div>

    </div><!-- /left -->

    <!-- RIGHT: Info & controls -->
    <div class="lg:col-span-2 space-y-3">

      <!-- Alert card (Mode 1) — dengan history -->
      <div id="alert-card" class="bg-gray-900 border border-gray-800 rounded-2xl p-4 relative overflow-hidden">
        <div class="absolute top-0 left-0 right-0 h-[3px] bg-gradient-to-r from-blue-500 to-purple-500"></div>
        <div class="flex justify-between items-center mb-2">
          <span class="text-[10px] text-gray-500 uppercase tracking-wider font-semibold">Riwayat Peringatan</span>
          <span id="source-badge"
            class="px-2 py-0.5 bg-gray-800 text-gray-500 text-[10px] rounded-lg border border-gray-700">
            Menunggu...
          </span>
        </div>
        <!-- Latest alert text -->
        <p id="alert-text" class="text-sm font-semibold text-blue-200 leading-snug mb-2">
          Menunggu koneksi dari kacamata...
        </p>
        <!-- History list -->
        <div id="alert-history" class="space-y-0.5 max-h-32 overflow-y-auto">
          <!-- diisi oleh JS -->
        </div>
      </div>

      <!-- Result card (Mode 2 / 3) -->
      <div id="result-card" class="hidden bg-gray-900 border border-gray-800 rounded-2xl p-4 relative overflow-hidden">
        <div id="result-bar" class="absolute top-0 left-0 right-0 h-[3px] bg-gradient-to-r from-green-500 to-cyan-400"></div>
        <div class="flex justify-between items-center mb-2">
          <span id="result-label" class="text-[10px] text-gray-500 uppercase tracking-wider">Hasil AI</span>
          <span id="result-type-badge"
            class="px-2 py-0.5 bg-green-900/30 text-green-300 text-[10px] rounded-lg border border-green-700">
            OCR
          </span>
        </div>
        <p id="result-text" class="text-sm text-white leading-relaxed min-h-[3rem]">—</p>
      </div>

      <!-- Processing indicator -->
      <div id="processing-card" class="hidden bg-gray-900 border border-gray-800 rounded-2xl p-4 flex items-center gap-3">
        <div class="h-5 w-5 border-2 border-blue-500 border-t-transparent rounded-full spin shrink-0"></div>
        <div>
          <p class="text-sm font-bold text-blue-300">Memproses AI...</p>
          <p class="text-[10px] text-gray-500">Sedang analisis dengan OpenAI Vision</p>
        </div>
      </div>

      <!-- Stats grid — Network & Device -->
      <div class="grid grid-cols-3 gap-1.5">
        <div class="bg-gray-900 border border-gray-800 rounded-xl p-2.5">
          <div class="text-[9px] text-gray-600 uppercase mb-0.5">Blur</div>
          <div id="stat-blur" class="text-sm font-mono font-bold text-white">—</div>
        </div>
        <div class="bg-gray-900 border border-gray-800 rounded-xl p-2.5">
          <div class="text-[9px] text-gray-600 uppercase mb-0.5">Objek</div>
          <div id="stat-objects" class="text-sm font-mono font-bold text-white">0</div>
        </div>
        <div class="bg-gray-900 border border-gray-800 rounded-xl p-2.5">
          <div class="text-[9px] text-gray-600 uppercase mb-0.5">Ping</div>
          <div id="stat-ping" class="text-sm font-mono font-bold text-white">—</div>
        </div>
        <div class="bg-gray-900 border border-gray-800 rounded-xl p-2.5">
          <div class="text-[9px] text-gray-600 uppercase mb-0.5">Baterai</div>
          <div id="stat-bat" class="text-sm font-mono font-bold text-white">—</div>
        </div>
        <div class="bg-gray-900 border border-gray-800 rounded-xl p-2.5">
          <div class="text-[9px] text-gray-600 uppercase mb-0.5">Jitter</div>
          <div id="stat-jitter" class="text-sm font-mono font-bold text-white">—</div>
        </div>
        <div class="bg-gray-900 border border-gray-800 rounded-xl p-2.5">
          <div class="text-[9px] text-gray-600 uppercase mb-0.5">Pkt Loss</div>
          <div id="stat-pktloss" class="text-sm font-mono font-bold text-white">—</div>
        </div>
      </div>

      <!-- AI Performance card -->
      <div class="bg-gray-900 border border-gray-800 rounded-2xl p-3 relative overflow-hidden">
        <div class="absolute top-0 left-0 right-0 h-[2px] bg-gradient-to-r from-violet-500 to-fuchsia-500"></div>
        <p class="text-[10px] text-gray-500 uppercase tracking-wider font-semibold mb-2.5">AI &amp; Hardware Performance</p>

        <!-- Inference / FPS row -->
        <div class="grid grid-cols-3 gap-1.5 mb-2.5">
          <div class="bg-gray-800/60 rounded-lg p-2 text-center">
            <div class="text-[9px] text-gray-600 uppercase">Inference</div>
            <div id="perf-infer" class="text-sm font-mono font-bold text-violet-300">—ms</div>
          </div>
          <div class="bg-gray-800/60 rounded-lg p-2 text-center">
            <div class="text-[9px] text-gray-600 uppercase">NPU FPS</div>
            <div id="perf-fps" class="text-sm font-mono font-bold text-fuchsia-300">—</div>
          </div>
          <div class="bg-gray-800/60 rounded-lg p-2 text-center">
            <div class="text-[9px] text-gray-600 uppercase">Suhu</div>
            <div id="perf-temp" class="text-sm font-mono font-bold text-orange-300">—°C</div>
          </div>
        </div>

        <!-- CPU bar -->
        <div class="mb-1.5">
          <div class="flex justify-between mb-0.5">
            <span class="text-[9px] text-gray-600 uppercase">CPU</span>
            <span id="perf-cpu-lbl" class="text-[9px] font-mono text-gray-500">—%</span>
          </div>
          <div class="bg-gray-800 rounded-full h-1.5">
            <div id="perf-cpu-bar" class="bg-blue-500 h-1.5 rounded-full transition-all" style="width:0%"></div>
          </div>
        </div>

        <!-- RAM bar -->
        <div>
          <div class="flex justify-between mb-0.5">
            <span class="text-[9px] text-gray-600 uppercase">RAM</span>
            <span id="perf-ram-lbl" class="text-[9px] font-mono text-gray-500">—/— MB</span>
          </div>
          <div class="bg-gray-800 rounded-full h-1.5">
            <div id="perf-ram-bar" class="bg-emerald-500 h-1.5 rounded-full transition-all" style="width:0%"></div>
          </div>
        </div>
      </div>

      <!-- Kontrol -->
      <div class="flex gap-2">
        <button id="tts-btn" onclick="toggleTTS()"
          class="flex-1 bg-gray-800 hover:bg-gray-700 border border-gray-700 text-white font-semibold py-3 rounded-xl text-sm transition btn-tap">
          &#128263; TTS Off
        </button>
        <button onclick="repeatLast()"
          class="flex-1 bg-blue-900/40 hover:bg-blue-900/70 border border-blue-800 text-blue-300 font-semibold py-3 rounded-xl text-sm transition btn-tap">
          &#128257; Ulangi
        </button>
      </div>

      <!-- Device Controls -->
      <div class="bg-gray-900 border border-gray-800 rounded-2xl p-4 relative overflow-hidden">
        <div class="absolute top-0 left-0 right-0 h-[3px] bg-gradient-to-r from-cyan-500 to-blue-500"></div>
        <div class="flex items-center justify-between mb-3">
          <p class="text-[10px] text-gray-500 uppercase tracking-wider font-semibold">Kontrol Device</p>
          <!-- Model status -->
          <div id="model-status-wrap" class="flex items-center gap-1.5">
            <div id="model-status-dot" class="h-2 w-2 rounded-full bg-gray-600"></div>
            <span id="model-status-label" class="text-[10px] text-gray-500 font-mono">idle</span>
          </div>
        </div>

        <!-- Mode buttons -->
        <div class="grid grid-cols-3 gap-1.5 mb-3">
          <button id="cb-mode1" onclick="ctrlMode(1)"
            class="mode-ctrl-btn bg-blue-900/30 hover:bg-blue-800/60 border border-blue-800 text-blue-300 font-semibold py-2.5 rounded-xl text-xs transition btn-tap">
            &#128269; Auto
          </button>
          <button id="cb-mode2" onclick="ctrlMode(2)"
            class="mode-ctrl-btn bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-300 font-semibold py-2.5 rounded-xl text-xs transition btn-tap">
            &#128218; OCR
          </button>
          <button id="cb-mode3" onclick="ctrlMode(3)"
            class="mode-ctrl-btn bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-300 font-semibold py-2.5 rounded-xl text-xs transition btn-tap">
            &#127748; Desc
          </button>
        </div>

        <!-- Scan button -->
        <button id="scan-btn" onclick="ctrlScan()"
          class="w-full bg-green-900/40 hover:bg-green-800/60 border border-green-700 text-green-300 font-bold py-3 rounded-xl text-sm transition btn-tap flex items-center justify-center gap-2">
          <span>&#128247;</span>
          <span id="scan-btn-label">Scan Sekarang</span>
        </button>
        <p class="text-[10px] text-gray-700 mt-2 text-center">Aktif saat Mode OCR atau Deskripsi</p>
      </div>

      <!-- Dev Panel (collapsible) -->
      <details class="bg-gray-900 border border-gray-800 rounded-2xl overflow-hidden group">
        <summary class="flex items-center justify-between px-4 py-3 hover:bg-gray-800/50 transition">
          <div class="flex items-center gap-2">
            <span class="text-[10px] text-gray-500 uppercase tracking-wider font-semibold">Dev Tools</span>
            <span class="text-[9px] text-gray-700">Tuning &amp; Debug</span>
          </div>
          <span class="chevron text-gray-600 text-sm">&#9654;</span>
        </summary>
        <div class="px-4 pb-4 space-y-3 border-t border-gray-800">

          <!-- Sliders -->
          <div class="pt-3 space-y-3">
            <div>
              <div class="flex justify-between mb-1">
                <label class="text-[10px] text-gray-500 uppercase">Confidence Threshold</label>
                <span id="lbl-conf" class="text-[10px] font-mono text-blue-300">0.45</span>
              </div>
              <input id="sl-conf" type="range" min="0.1" max="1.0" step="0.05" value="0.45"
                oninput="document.getElementById('lbl-conf').textContent=parseFloat(this.value).toFixed(2); scheduleSettingsApply()"
                class="w-full h-1.5 rounded-full">
            </div>
            <div>
              <div class="flex justify-between mb-1">
                <label class="text-[10px] text-gray-500 uppercase">IoU / NMS Threshold</label>
                <span id="lbl-iou" class="text-[10px] font-mono text-blue-300">0.45</span>
              </div>
              <input id="sl-iou" type="range" min="0.1" max="1.0" step="0.05" value="0.45"
                oninput="document.getElementById('lbl-iou').textContent=parseFloat(this.value).toFixed(2); scheduleSettingsApply()"
                class="w-full h-1.5 rounded-full">
            </div>
            <div>
              <div class="flex justify-between mb-1">
                <label class="text-[10px] text-gray-500 uppercase">Blur Threshold</label>
                <span id="lbl-blur" class="text-[10px] font-mono text-blue-300">50</span>
              </div>
              <input id="sl-blur" type="range" min="5" max="200" step="5" value="50"
                oninput="document.getElementById('lbl-blur').textContent=this.value; scheduleSettingsApply()"
                class="w-full h-1.5 rounded-full">
            </div>
            <!-- Bounding Box Toggle -->
            <div class="flex items-center justify-between pt-1 border-t border-gray-800">
              <div>
                <label class="text-[10px] text-gray-500 uppercase font-semibold">Bounding Box</label>
                <p class="text-[9px] text-gray-700">Tampilkan kotak &amp; label keyakinan di preview</p>
              </div>
              <button id="bbox-toggle" onclick="toggleBbox()"
                class="relative inline-flex h-5 w-9 items-center rounded-full bg-blue-600 transition-colors">
                <span id="bbox-thumb" class="inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform translate-x-4"></span>
              </button>
            </div>
            <div id="settings-status" class="text-[10px] text-gray-700 text-right">—</div>
          </div>

          <!-- Debug Console -->
          <div>
            <div class="flex items-center justify-between mb-1.5">
              <span class="text-[10px] text-gray-600 uppercase font-semibold">Debug Console</span>
              <button onclick="clearDebug()" class="text-[9px] text-gray-700 hover:text-gray-500">Clear</button>
            </div>
            <div id="debug-console"
              class="bg-gray-950 border border-gray-800 rounded-lg p-2 h-28 overflow-y-auto font-mono text-[10px] text-green-500/80 space-y-0.5">
              <div class="text-gray-700">— console aktif setelah device terhubung —</div>
            </div>
          </div>

          <!-- Raw JSON Payload Inspector -->
          <div>
            <div class="flex items-center justify-between mb-1.5">
              <span class="text-[10px] text-gray-600 uppercase font-semibold">Raw JSON Inspector</span>
              <div class="flex gap-1">
                <button id="raw-tab-update" onclick="switchRawTab('update')"
                  class="px-2 py-0.5 text-[9px] bg-blue-900/50 border border-blue-800 text-blue-300 rounded font-mono">update</button>
                <button id="raw-tab-ping" onclick="switchRawTab('ping')"
                  class="px-2 py-0.5 text-[9px] bg-gray-800 border border-gray-700 text-gray-500 rounded font-mono">ping</button>
              </div>
            </div>
            <pre id="raw-json"
              class="bg-gray-950 border border-gray-800 rounded-lg p-2 h-36 overflow-auto font-mono text-[10px] text-cyan-400/80 whitespace-pre-wrap break-all">— menunggu data —</pre>
            <p id="raw-age" class="text-[9px] text-gray-700 mt-0.5 text-right">—</p>
          </div>

        </div>
      </details>

      <!-- Info cara pakai -->
      <div class="bg-gray-900/60 border border-gray-800/50 rounded-xl px-3 py-2.5 space-y-1">
        <p class="text-[10px] text-gray-600 uppercase tracking-wider mb-1">Cara Pakai</p>
        <p class="text-[11px] text-gray-500">&#127381; Jalankan <code class="text-gray-400">webserver.py</code> di PC</p>
        <p class="text-[11px] text-gray-500">&#128187; Test desktop: <code class="text-gray-400">run_on_desktop.py</code></p>
        <p class="text-[11px] text-gray-500">&#128247; Di MaixCam: <code class="text-gray-400">run_on_maix.py</code></p>
      </div>

    </div><!-- /right -->
  </div><!-- /grid -->
</div><!-- /max-w-5xl -->

<script>
// ─── State ────────────────────────────────────────────────
let isTtsEnabled   = false;
let jsQueue        = [];
let isSpeaking     = false;
let lastAlert      = "";
let lastSpeechId   = 0;
let lastData       = null;
let lastResultTxt  = "";
let camSignalOk    = false;
let camRetryTimer  = null;
let _settingsTimer = null;
let _debugOffset   = 0;

const MODE_ICONS  = {"1":"&#128269;", "2":"&#128218;", "3":"&#127748;"};
const MODE_NAMES  = {"1":"Deteksi Objek", "2":"Baca Teks (OCR)", "3":"Deskripsi Adegan"};
const MODE_COLORS = {
  "1": {badge:"bg-blue-900/30 text-blue-300 border-blue-800"},
  "2": {badge:"bg-green-900/30 text-green-300 border-green-800"},
  "3": {badge:"bg-purple-900/30 text-purple-300 border-purple-800"},
};

// ─── Camera stream ────────────────────────────────────────
function camLoaded() {
  camSignalOk = true;
  clearTimeout(camRetryTimer);
  document.getElementById("cam-nosignal").style.display = "none";
  document.getElementById("cam-dot").className   = "h-2 w-2 rounded-full bg-green-500 pulse";
  document.getElementById("cam-label").textContent = "LIVE";
  document.getElementById("cam-label").className   = "text-[10px] text-green-400 font-mono";
}
function camError() {
  camSignalOk = false;
  document.getElementById("cam-nosignal").style.display = "";
  document.getElementById("cam-dot").className   = "h-2 w-2 rounded-full bg-gray-700";
  document.getElementById("cam-label").textContent = "no signal";
  document.getElementById("cam-label").className   = "text-[10px] text-gray-600 font-mono";
  // Retry setelah 3 detik
  clearTimeout(camRetryTimer);
  camRetryTimer = setTimeout(() => {
    const img = document.getElementById("cam-img");
    img.src = "/api/stream?" + Date.now();
  }, 3000);
}

// ─── TTS engine ───────────────────────────────────────────
function rawSpeak(text) {
  if (!isTtsEnabled || !text) return;
  isSpeaking = true;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang  = "id-ID";
  u.rate  = 1.15;
  u.pitch = 1.0;
  u.onend  = () => { isSpeaking = false; processQueue(); };
  u.onerror = () => { isSpeaking = false; processQueue(); };
  window.speechSynthesis.speak(u);
}
function enqueue(text, priority = 1) {
  if (!text || !isTtsEnabled) return;
  if (priority >= 10) jsQueue.unshift(text);
  else jsQueue.push(text);
  if (!isSpeaking) processQueue();
}
function processQueue() {
  if (isSpeaking || jsQueue.length === 0 || !isTtsEnabled) return;
  rawSpeak(jsQueue.shift());
}

// ─── UI helpers ───────────────────────────────────────────
function setOnline(online) {
  const dot = document.getElementById("status-dot");
  const txt = document.getElementById("status-text");
  dot.className = online
    ? "h-2.5 w-2.5 rounded-full bg-green-500 pulse"
    : "h-2.5 w-2.5 rounded-full bg-red-500";
  txt.textContent = online ? "ONLINE" : "OFFLINE";
  txt.className   = online
    ? "text-xs font-bold text-green-400 tracking-wider"
    : "text-xs font-bold text-red-400 tracking-wider";
}

function setModeUI(modeId, modeName) {
  const key = String(modeId);
  const c   = MODE_COLORS[key] || MODE_COLORS["1"];
  const ico = MODE_ICONS[key]  || "&#128269;";
  const nm  = modeName || MODE_NAMES[key] || "—";
  const lbl = "Mode " + modeId;

  // Desktop header
  document.getElementById("mode-icon").innerHTML    = ico;
  document.getElementById("mode-name").textContent  = nm;
  const mb = document.getElementById("mode-badge");
  mb.textContent = lbl;
  mb.className   = `px-2 py-0.5 text-[10px] rounded-lg font-mono border shrink-0 ${c.badge}`;

  // Mobile
  document.getElementById("mode-icon-m").innerHTML   = ico;
  document.getElementById("mode-name-m").textContent = nm;
  const mbm = document.getElementById("mode-badge-m");
  mbm.textContent = lbl;
  mbm.className   = `px-2 py-0.5 text-[10px] rounded-lg font-mono border shrink-0 ${c.badge}`;

  const isObj = (modeId === 1);
  document.getElementById("alert-card").style.display       = isObj ? "" : "none";
  document.getElementById("objects-section").style.display  = isObj ? "" : "none";
  if (!isObj && lastResultTxt) {
    document.getElementById("result-card").classList.remove("hidden");
  }
}

function updateObjectsGrid(objects) {
  const grid = document.getElementById("objects-grid");
  document.getElementById("stat-objects").textContent = objects ? objects.length : 0;
  if (!objects || objects.length === 0) {
    grid.innerHTML =
      '<div class="col-span-2 sm:col-span-3 bg-gray-900 border border-gray-800 rounded-xl p-3 text-center text-gray-600 text-sm">Tidak ada objek terdeteksi</div>';
    return;
  }
  grid.innerHTML = objects.map(o => {
    const danger    = o.warning === "terlalu dekat";
    const cardCls   = danger
      ? "bg-red-950/40 border border-red-700/50 rounded-xl p-3"
      : "bg-gray-900 border border-gray-800 rounded-xl p-3";
    const lblCls    = danger ? "font-bold text-red-300 text-sm" : "font-bold text-white text-sm";
    const warnBadge = danger
      ? '<span class="text-[10px] bg-red-700/50 text-red-200 px-1.5 py-0.5 rounded-full">! DEKAT</span>'
      : '<span class="text-[10px] bg-gray-700/80 text-gray-400 px-1.5 py-0.5 rounded-full">aman</span>';
    return `<div class="${cardCls}">
      <div class="flex justify-between items-start mb-1">
        <span class="${lblCls}">${o.label}</span>${warnBadge}
      </div>
      <div class="text-xs text-gray-500">${o.position} &bull; ${Math.round((o.score||0)*100)}%</div>
    </div>`;
  }).join("");
}

function showResult(text, stype) {
  lastResultTxt = text;
  document.getElementById("result-text").textContent = text;
  document.getElementById("result-card").classList.remove("hidden");
  document.getElementById("processing-card").classList.add("hidden");
  const isOCR = stype === "ocr";
  document.getElementById("result-bar").className =
    "absolute top-0 left-0 right-0 h-[3px] bg-gradient-to-r " +
    (isOCR ? "from-green-500 to-cyan-400" : "from-purple-500 to-pink-500");
  document.getElementById("result-label").textContent =
    isOCR ? "Teks Terbaca" : "Deskripsi Adegan";
  const tbadge = document.getElementById("result-type-badge");
  tbadge.textContent = isOCR ? "OCR" : "AI Vision";
  tbadge.className   = "px-2 py-0.5 text-[10px] rounded-lg border " +
    (isOCR ? "bg-green-900/30 text-green-300 border-green-700"
           : "bg-purple-900/30 text-purple-300 border-purple-700");
}

// ─── Polling /api/status ──────────────────────────────────
async function pollStatus() {
  try {
    const res  = await fetch("/api/status");
    const data = await res.json();
    lastData   = data;

    setOnline(data.is_online);

    const modeId   = data.mode || 1;
    const modeName = data.mode_name || MODE_NAMES[String(modeId)] || "Deteksi Objek";
    setModeUI(modeId, modeName);
    syncCtrlBtns(modeId);

    // Blur
    const blurScore = (data.camera && data.camera.blur_score) || 0;
    const blurOn    = data.camera && data.camera.is_blur && data.is_online;
    document.getElementById("stat-blur").textContent  = blurScore ? blurScore.toFixed(1) : "—";
    document.getElementById("blur-alert").classList.toggle("hidden", !blurOn);

    if (modeId === 1 && data.is_online) {
      const alertMsg = data.speech_alert || "";
      document.getElementById("alert-text").textContent =
        alertMsg || "Aman, tidak ada objek terdeteksi.";
      const sb = document.getElementById("source-badge");
      if (data.alert_source === "openai") {
        sb.textContent = "OpenAI";
        sb.className   = "px-2 py-0.5 bg-purple-900/30 text-purple-300 text-[10px] rounded-lg border border-purple-700";
      } else {
        sb.textContent = "Lokal";
        sb.className   = "px-2 py-0.5 bg-yellow-900/30 text-yellow-300 text-[10px] rounded-lg border border-yellow-700";
      }
      if (alertMsg && alertMsg !== lastAlert && !blurOn) {
        lastAlert = alertMsg;
        enqueue(alertMsg, 2);
      }
      updateObjectsGrid(data.objects || []);
    }

    if (data.last_result && data.last_result !== lastResultTxt) {
      showResult(data.last_result, modeId === 2 ? "ocr" : "describe");
    }

    // Telemetry
    if (data.telemetry) { updateTelemetry(data.telemetry); updateAIPerf(data.telemetry); }

    // Alert history
    if (data.alert_history) updateAlertHistory(data.alert_history);

    // Model status
    if (data.model_status) updateModelStatus(data.model_status);

    // Sync sliders dengan settings server (satu kali saat load)
    if (data.settings && !_settingsSynced) {
      _settingsSynced = true;
      syncSliders(data.settings);
    }

  } catch (e) {
    console.error("pollStatus:", e);
  }
}
let _settingsSynced = false;

// ─── Polling /api/speech_poll ─────────────────────────────
async function pollSpeechQueue() {
  try {
    const res  = await fetch(`/api/speech_poll?since_id=${lastSpeechId}`);
    const data = await res.json();
    if (!data.items) return;
    for (const item of data.items) {
      if (item.id <= lastSpeechId) continue;
      lastSpeechId = item.id;
      const priority = item.type === "system" ? 10 : (item.priority || 3);
      enqueue(item.text, priority);
      if (item.type === "ocr" || item.type === "describe") {
        showResult(item.text, item.type);
      }
      if (item.type === "processing") {
        document.getElementById("processing-card").classList.remove("hidden");
        document.getElementById("result-card").classList.add("hidden");
      }
    }
  } catch (e) {
    console.error("pollSpeechQueue:", e);
  }
}

// ─── Kontrol ──────────────────────────────────────────────
function toggleTTS() {
  isTtsEnabled = !isTtsEnabled;
  const btn = document.getElementById("tts-btn");
  if (isTtsEnabled) {
    btn.innerHTML = "&#128263; TTS Off";
    enqueue("Suara diaktifkan.", 10);
  } else {
    window.speechSynthesis.cancel();
    jsQueue    = [];
    isSpeaking = false;
    btn.innerHTML = "&#128264; TTS On";
  }
}

function repeatLast() {
  if (!isTtsEnabled) { isTtsEnabled = true; }
  const text = (lastData && lastData.speech_alert) || lastResultTxt || "Belum ada pesan.";
  window.speechSynthesis.cancel();
  isSpeaking = false;
  jsQueue    = [];
  rawSpeak(text);
}

// ─── Telemetry ────────────────────────────────────────────
function updateTelemetry(t) {
  // Header compact
  const bat  = t.battery_pct != null ? t.battery_pct + "%" : "—%";
  const ping = t.ping_ms     != null ? Math.round(t.ping_ms) + "ms" : "—ms";
  const temp = t.cpu_temp_c  != null ? Math.round(t.cpu_temp_c) + "°C" : "—°C";
  document.getElementById("tl-bat").textContent  = bat;
  document.getElementById("tl-ping").textContent = ping;
  document.getElementById("tl-temp").textContent = temp;

  // Battery icon color
  const batIcon = document.getElementById("tl-bat-icon");
  if (t.battery_pct != null) {
    batIcon.textContent = t.battery_pct > 50 ? "&#128267;" : t.battery_pct > 20 ? "&#128266;" : "&#128265;";
    document.getElementById("tl-bat").className =
      "text-[11px] font-mono " + (t.battery_pct > 50 ? "text-green-400" : t.battery_pct > 20 ? "text-yellow-400" : "text-red-400");
  }

  // Ping color
  document.getElementById("tl-ping").className =
    "text-[11px] font-mono " + (t.ping_ms == null ? "text-gray-400" : t.ping_ms < 100 ? "text-green-400" : t.ping_ms < 300 ? "text-yellow-400" : "text-red-400");

  // Temp color + thermal banner
  document.getElementById("tl-temp").className =
    "text-[11px] font-mono " + (t.cpu_temp_c == null ? "text-gray-400" : t.cpu_temp_c < 70 ? "text-green-400" : t.cpu_temp_c < 80 ? "text-yellow-400" : "text-red-400");

  const banner = document.getElementById("thermal-banner");
  if (t.cpu_temp_c != null && t.cpu_temp_c >= 75) {
    banner.classList.add("show");
    document.getElementById("thermal-detail").textContent =
      `Suhu SoC: ${t.cpu_temp_c.toFixed(1)}°C — ${t.cpu_temp_c >= 85 ? "Throttling aktif!" : "Mendekati batas throttling"}`;
  } else {
    banner.classList.remove("show");
  }

  // Stats grid
  document.getElementById("stat-ping").textContent = t.ping_ms  != null ? Math.round(t.ping_ms)+"ms" : "—";
  document.getElementById("stat-bat").textContent  = t.battery_pct != null ? t.battery_pct+"%" : "—";
  document.getElementById("stat-wifi").textContent = t.wifi_dbm != null ? t.wifi_dbm+"dBm" : "—";
  const tempEl = document.getElementById("stat-temp");
  tempEl.textContent = t.cpu_temp_c != null ? t.cpu_temp_c.toFixed(1)+"°C" : "—";
  tempEl.className = "text-base font-mono font-bold " + (t.cpu_temp_c == null ? "text-white" : t.cpu_temp_c < 70 ? "text-green-400" : t.cpu_temp_c < 80 ? "text-yellow-400" : "text-red-400");
}

// ─── Alert History ────────────────────────────────────────
const HIST_TYPE_CLS = {
  warning:  "text-red-400",
  alert:    "text-red-400",
  ocr:      "text-green-400",
  describe: "text-purple-400",
  system:   "text-blue-400",
  info:     "text-gray-400",
};
function updateAlertHistory(hist) {
  const el = document.getElementById("alert-history");
  if (!hist || hist.length === 0) return;
  el.innerHTML = hist.map(h => {
    const cls = HIST_TYPE_CLS[h.type] || "text-gray-500";
    return `<div class="flex gap-1.5 items-start py-0.5 border-b border-gray-800/50 last:border-0">
      <span class="text-gray-600 font-mono text-[9px] shrink-0 pt-0.5">${h.ts}</span>
      <span class="text-[10px] ${cls} leading-tight">${h.text}</span>
    </div>`;
  }).join("");
}

// ─── Model Status ─────────────────────────────────────────
const MS_CONFIG = {
  idle:         {dot:"bg-gray-600",     label:"text-gray-500",  text:"idle"},
  loading:      {dot:"bg-yellow-500 pulse", label:"text-yellow-400", text:"loading model..."},
  inferencing:  {dot:"bg-blue-500 pulse",  label:"text-blue-400",   text:"inferencing"},
};
function updateModelStatus(ms) {
  const cfg = MS_CONFIG[ms.status] || MS_CONFIG.idle;
  document.getElementById("model-status-dot").className   = `h-2 w-2 rounded-full ${cfg.dot}`;
  document.getElementById("model-status-label").className = `text-[10px] font-mono ${cfg.label}`;
  document.getElementById("model-status-label").textContent = ms.detail ? `${cfg.text} (${ms.detail})` : cfg.text;
}

// ─── Capture / Flag ──────────────────────────────────────
async function captureSnapshot(flagged) {
  const btn = flagged ? document.getElementById("flag-btn") : document.getElementById("snap-btn");
  const origText = btn.innerHTML;
  btn.innerHTML = "&#8987; ...";
  btn.disabled  = true;
  try {
    const r = await fetch("/api/capture", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({flagged}),
    });
    const d = await r.json();
    if (d.status === "ok") {
      btn.innerHTML = flagged ? "&#10003; Tersimpan!" : "&#10003; Saved!";
      setTimeout(() => { btn.innerHTML = origText; btn.disabled = false; }, 2000);
    } else {
      btn.innerHTML = "&#10007; Gagal";
      setTimeout(() => { btn.innerHTML = origText; btn.disabled = false; }, 2000);
    }
  } catch(e) {
    btn.innerHTML = "&#10007; Error";
    setTimeout(() => { btn.innerHTML = origText; btn.disabled = false; }, 2000);
  }
}

// ─── Settings sliders ────────────────────────────────────
function syncSliders(cfg) {
  if (cfg.conf_threshold != null) {
    document.getElementById("sl-conf").value = cfg.conf_threshold;
    document.getElementById("lbl-conf").textContent = parseFloat(cfg.conf_threshold).toFixed(2);
  }
  if (cfg.iou_threshold != null) {
    document.getElementById("sl-iou").value = cfg.iou_threshold;
    document.getElementById("lbl-iou").textContent = parseFloat(cfg.iou_threshold).toFixed(2);
  }
  if (cfg.blur_threshold != null) {
    document.getElementById("sl-blur").value = cfg.blur_threshold;
    document.getElementById("lbl-blur").textContent = cfg.blur_threshold;
  }
  if (cfg.show_bbox != null) {
    _bboxOn = cfg.show_bbox;
    const btn   = document.getElementById("bbox-toggle");
    const thumb = document.getElementById("bbox-thumb");
    if (btn)   btn.className   = `relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${_bboxOn ? "bg-blue-600" : "bg-gray-700"}`;
    if (thumb) thumb.className = `inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${_bboxOn ? "translate-x-4" : "translate-x-1"}`;
  }
}
function scheduleSettingsApply() {
  clearTimeout(_settingsTimer);
  document.getElementById("settings-status").textContent = "mengetik...";
  _settingsTimer = setTimeout(applySettings, 600);
}
async function applySettings() {
  const payload = {
    conf_threshold: parseFloat(document.getElementById("sl-conf").value),
    iou_threshold:  parseFloat(document.getElementById("sl-iou").value),
    blur_threshold: parseFloat(document.getElementById("sl-blur").value),
  };
  try {
    const r = await fetch("/api/settings", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload),
    });
    const d = await r.json();
    document.getElementById("settings-status").textContent =
      d.status === "ok" ? "&#10003; diterapkan" : "&#10007; gagal";
  } catch(e) {
    document.getElementById("settings-status").textContent = "&#10007; error";
  }
}

// ─── Debug console ───────────────────────────────────────
async function pollDebugLog() {
  try {
    const r = await fetch(`/api/debug_log?since=${_debugOffset}`);
    const d = await r.json();
    if (!d.entries || d.entries.length === 0) return;
    const el = document.getElementById("debug-console");
    const wasAtBottom = el.scrollHeight - el.scrollTop <= el.clientHeight + 10;
    const placeholder = el.querySelector(".text-gray-700");
    if (placeholder) placeholder.remove();
    for (const e of d.entries) {
      const div = document.createElement("div");
      div.className = "text-green-500/70";
      div.textContent = `${e.ts} | ${e.msg}`;
      el.appendChild(div);
      _debugOffset++;
    }
    // Limit DOM nodes
    while (el.children.length > 100) el.removeChild(el.firstChild);
    if (wasAtBottom) el.scrollTop = el.scrollHeight;
  } catch(e) {}
}
function clearDebug() {
  document.getElementById("debug-console").innerHTML =
    '<div class="text-gray-700">— cleared —</div>';
  _debugOffset = 0;
}

function startApp() {
  isTtsEnabled = true;
  document.getElementById("overlay").classList.add("hidden");
  rawSpeak("Sistem Sonara aktif.");
  setInterval(pollStatus,      400);
  setInterval(pollSpeechQueue, 800);
  setInterval(pollDebugLog,   1500);
  setInterval(pollRawPayload, 1200);
  setTimeout(() => { if (!camSignalOk) camError(); }, 4000);
}

// ─── AI Performance & extended telemetry ─────────────────
function updateAIPerf(t) {
  // Inference & FPS
  document.getElementById("perf-infer").textContent = t.inference_ms != null ? t.inference_ms + "ms" : "—ms";
  document.getElementById("perf-fps").textContent   = t.kpu_fps      != null ? t.kpu_fps + " fps" : "—";
  document.getElementById("perf-temp").textContent  = t.cpu_temp_c   != null ? t.cpu_temp_c.toFixed(1) + "°C" : "—°C";
  // CPU bar
  const cpu = t.cpu_pct;
  document.getElementById("perf-cpu-lbl").textContent = cpu != null ? cpu + "%" : "—%";
  const cpuBar = document.getElementById("perf-cpu-bar");
  cpuBar.style.width = (cpu != null ? Math.min(cpu, 100) : 0) + "%";
  cpuBar.className = "h-1.5 rounded-full transition-all " +
    (cpu == null ? "bg-gray-600" : cpu < 70 ? "bg-blue-500" : cpu < 90 ? "bg-yellow-500" : "bg-red-500");
  // RAM bar
  const used = t.ram_used_mb, total = t.ram_total_mb;
  document.getElementById("perf-ram-lbl").textContent = (used != null && total != null)
    ? `${used}/${total} MB` : "—/— MB";
  const ramPct = (used != null && total != null && total > 0) ? (used / total * 100) : 0;
  const ramBar = document.getElementById("perf-ram-bar");
  ramBar.style.width = ramPct + "%";
  ramBar.className = "h-1.5 rounded-full transition-all " +
    (ramPct < 60 ? "bg-emerald-500" : ramPct < 85 ? "bg-yellow-500" : "bg-red-500");
  // Jitter & Packet Loss
  if (t.jitter_ms != null) {
    document.getElementById("stat-jitter").textContent = t.jitter_ms + "ms";
    document.getElementById("stat-jitter").className   = "text-sm font-mono font-bold " +
      (t.jitter_ms < 20 ? "text-green-400" : t.jitter_ms < 80 ? "text-yellow-400" : "text-red-400");
  }
  if (t.packet_loss_pct != null) {
    document.getElementById("stat-pktloss").textContent = t.packet_loss_pct + "%";
    document.getElementById("stat-pktloss").className   = "text-sm font-mono font-bold " +
      (t.packet_loss_pct === 0 ? "text-green-400" : t.packet_loss_pct < 5 ? "text-yellow-400" : "text-red-400");
  }
}

// ─── Bounding Box toggle ──────────────────────────────────
let _bboxOn = true;
function toggleBbox() {
  _bboxOn = !_bboxOn;
  const btn   = document.getElementById("bbox-toggle");
  const thumb = document.getElementById("bbox-thumb");
  btn.className   = `relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${_bboxOn ? "bg-blue-600" : "bg-gray-700"}`;
  thumb.className = `inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${_bboxOn ? "translate-x-4" : "translate-x-1"}`;
  fetch("/api/settings", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({show_bbox: _bboxOn}),
  }).catch(() => {});
  document.getElementById("settings-status").textContent = `bbox: ${_bboxOn ? "ON" : "OFF"}`;
}

// ─── Raw JSON Inspector ───────────────────────────────────
let _rawTab = "update";
let _rawPollTimer = null;

function switchRawTab(tab) {
  _rawTab = tab;
  document.getElementById("raw-tab-update").className =
    `px-2 py-0.5 text-[9px] rounded font-mono border ${tab === "update" ? "bg-blue-900/50 border-blue-800 text-blue-300" : "bg-gray-800 border-gray-700 text-gray-500"}`;
  document.getElementById("raw-tab-ping").className =
    `px-2 py-0.5 text-[9px] rounded font-mono border ${tab === "ping" ? "bg-blue-900/50 border-blue-800 text-blue-300" : "bg-gray-800 border-gray-700 text-gray-500"}`;
  pollRawPayload();
}

async function pollRawPayload() {
  try {
    const r = await fetch("/api/latest_payload");
    const d = await r.json();
    const payload = _rawTab === "update" ? d.update : d.ping;
    document.getElementById("raw-json").textContent =
      Object.keys(payload).length ? JSON.stringify(payload, null, 2) : "— tidak ada data —";
    if (_rawTab === "update" && d.update_age_s != null) {
      document.getElementById("raw-age").textContent = `${d.update_age_s}s lalu`;
    }
  } catch(e) {}
}

// ─── Device controls (kirim command ke server) ─────────────
let _activeCtrlMode = 1;

async function ctrlMode(m) {
  _activeCtrlMode = m;
  _updateCtrlBtns(m);
  try {
    await fetch("/api/command", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({type: "set_mode", mode: m}),
    });
  } catch(e) { console.error(e); }
  // Update scan button state
  const scanBtn = document.getElementById("scan-btn");
  if (m === 2 || m === 3) {
    scanBtn.classList.remove("opacity-40", "cursor-not-allowed");
    scanBtn.disabled = false;
  } else {
    scanBtn.classList.add("opacity-40");
    scanBtn.disabled = false;
  }
}

async function ctrlScan() {
  const lbl = document.getElementById("scan-btn-label");
  lbl.textContent = "Memproses...";
  document.getElementById("scan-btn").disabled = true;
  try {
    await fetch("/api/command", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({type: "scan"}),
    });
    // Tampilkan spinner
    document.getElementById("processing-card").classList.remove("hidden");
    document.getElementById("result-card").classList.add("hidden");
  } catch(e) { console.error(e); }
  setTimeout(() => {
    lbl.textContent = "Scan Sekarang";
    document.getElementById("scan-btn").disabled = false;
  }, 3000);
}

function _updateCtrlBtns(active) {
  const configs = {
    1: {id:"cb-mode1", on:"bg-blue-900/30 border-blue-800 text-blue-300",   off:"bg-gray-800 border-gray-700 text-gray-300"},
    2: {id:"cb-mode2", on:"bg-green-900/30 border-green-800 text-green-300", off:"bg-gray-800 border-gray-700 text-gray-300"},
    3: {id:"cb-mode3", on:"bg-purple-900/30 border-purple-800 text-purple-300", off:"bg-gray-800 border-gray-700 text-gray-300"},
  };
  for (const [m, c] of Object.entries(configs)) {
    const btn = document.getElementById(c.id);
    if (!btn) continue;
    const isActive = (parseInt(m) === active);
    // remove both, then add correct
    c.on.split(" ").forEach(cls  => btn.classList.toggle(cls,  isActive));
    c.off.split(" ").forEach(cls => btn.classList.toggle(cls, !isActive));
  }
}

// Sync tombol kontrol dengan mode yang dilaporkan device
function syncCtrlBtns(modeId) {
  if (modeId && modeId !== _activeCtrlMode) {
    _activeCtrlMode = modeId;
    _updateCtrlBtns(modeId);
  }
}
</script>
</body>
</html>"""


@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


# ============================================================
# UTILS + ENTRY POINT
# ============================================================
def get_local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


if __name__ == "__main__":
    LAN_IP = get_local_ip()
    print("=" * 58)
    print("  SERVER SONARA AKTIF")
    print(f"  IP PC    : {LAN_IP}")
    print(f"  URL HP   : http://{LAN_IP}:{HOST_PORT}")
    print(f"  MaixCam  : set  HOST_IP = \"{LAN_IP}\"  di run_on_maix.py")
    print("=" * 58)
    app.run(host="0.0.0.0", port=HOST_PORT, debug=False)

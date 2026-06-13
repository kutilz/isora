"""
AI Engine — Camera capture, NPU inference, result processing.
Runs inside the AI loop thread.

Resource lifecycle
──────────────────
  release_model()   Free YOLO from NPU memory (called when switching to context/qris mode).
  reload_model()    Reload YOLO after mode returns to explorer.
  release()         Full teardown: camera + model (called by watchdog restart).
  reload()          Full reinit: camera + model (watchdog restart_fn).
"""

import time
import base64
import threading

try:
    from maix import camera, nn, image
    MAIX_AVAILABLE = True
except ImportError:
    MAIX_AVAILABLE = False

from config import cfg, RELEVANT_LABELS, COCO_LABEL_MAP
from utils.logger import position_from_bbox
from adapters import get_adapter, AdapterError


class AIEngine:

    def __init__(self, orchestrator, logger):
        self.orch   = orchestrator
        self.logger = logger

        self._cam:          object = None
        self._detector:     object = None
        self._model_loaded: bool   = False
        self._last_frame:   object = None
        self._lock = threading.Lock()

        # Gentle camera recovery: when the camera is down, retry at most once
        # per interval instead of letting the watchdog hammer reload() every
        # few seconds (which leaks VI buffers until the C layer segfaults).
        self._last_cam_retry      = 0.0
        self._cam_retry_interval_s = 30.0

        # Throttle for cloud pairing QR scans (only active while unpaired).
        self._last_qr_scan = 0.0

        # Temporal de-flicker tracker. A label must persist in roughly the same
        # spot for several consecutive frames before it counts as a real
        # detection. Kills YOLO phantom boxes that flicker/teleport on a covered
        # or blurred lens (the "keeps announcing a person with the camera
        # covered" failure mode). label -> {"cx", "cy", "streak"}.
        self._track: dict = {}

        self._init_camera()
        self._init_model()

    # ─── Init helpers ─────────────────────────────────────────────────────────

    def _init_camera(self):
        if not MAIX_AVAILABLE:
            self.logger.warn("MaixPy unavailable — camera skipped", module="AIEngine")
            return
        try:
            self._cam = camera.Camera(
                cfg.INPUT_WIDTH, cfg.INPUT_HEIGHT, image.Format.FMT_RGB888
            )
            self._cam.open()
            self.logger.ok(
                f"Camera: {cfg.INPUT_WIDTH}×{cfg.INPUT_HEIGHT} @ {cfg.CAMERA_FPS}fps",
                module="AIEngine",
            )
        except Exception as e:
            self.logger.error(f"Camera init failed: {e}", module="AIEngine")
            self._cam = None

    def _init_model(self):
        if not MAIX_AVAILABLE:
            self.logger.warn("MaixPy unavailable — model skipped", module="AIEngine")
            return
        try:
            self._detector    = nn.YOLO11(model=cfg.MODEL_PATH)
            self._model_loaded = True
            self.logger.ok(f"YOLO11 loaded: {cfg.MODEL_PATH}", module="AIEngine")
        except Exception as e:
            self.logger.error(f"Model load failed: {e}", module="AIEngine")
            self._model_loaded = False

    # ─── Resource management (called by Orchestrator on mode switch) ──────────

    def release_model(self):
        """Unload YOLO from NPU to free memory. Camera stays open."""
        with self._lock:
            if self._detector is not None:
                try:
                    del self._detector
                except Exception:
                    pass
                self._detector     = None
                self._model_loaded = False
                self.logger.info("YOLO model released (NPU free)", module="AIEngine")

    def reload_model(self):
        """Reload YOLO. No-op if already loaded."""
        with self._lock:
            if self._model_loaded:
                return
        self._init_model()

    def release(self):
        """Full teardown — camera + model. Called before watchdog restart."""
        self.release_model()
        with self._lock:
            if self._cam is not None:
                try:
                    self._cam.close()
                except Exception:
                    pass
                self._cam = None

    def reload(self):
        """Full reinit after a crash. Used as watchdog restart_fn."""
        self.logger.warn("Reloading AI Engine (watchdog triggered)", module="AIEngine")
        self.release()
        time.sleep(0.5)
        self._init_camera()
        self._init_model()

    def _maybe_recover_camera(self):
        """Rate-limited camera re-init while the camera is down (no hammering)."""
        if not MAIX_AVAILABLE:
            return
        now = time.monotonic()
        if now - self._last_cam_retry < self._cam_retry_interval_s:
            return
        self._last_cam_retry = now
        self.logger.warn(
            "Camera unavailable — retrying init (30s backoff)", module="AIEngine"
        )
        self._init_camera()
        if self._cam is not None and not self._model_loaded:
            self._init_model()

    # ─── Main pipeline ────────────────────────────────────────────────────────

    def capture_and_infer(self):
        """
        Capture one frame, run YOLO if loaded, return:
          (jpeg_bytes, detections_list, latency_dict)
        Returns (None, [], {}) on camera failure.
        """
        if not MAIX_AVAILABLE or self._cam is None:
            self._track = {}            # drop stale tracks across a camera gap
            self._maybe_recover_camera()
            return None, [], {}

        t0 = time.time()

        # ── Camera read with single auto-recover ──────────────────────────────
        try:
            frame = self._cam.read()
        except RuntimeError as e:
            self.logger.warn(f"Camera read error ({e}) — attempting reopen",
                             module="AIEngine")
            try:
                self._cam.close()
            except Exception:
                pass
            time.sleep(0.3)
            try:
                self._cam.open()
                frame = self._cam.read()
                self.logger.ok("Camera recovered", module="AIEngine")
            except Exception as e2:
                self.logger.error(f"Camera reopen failed: {e2}", module="AIEngine")
                return None, [], {}

        t_cam = (time.time() - t0) * 1000
        self._last_frame = frame

        jpeg = frame.to_jpeg()
        self.orch.snapshot = bytes(jpeg.to_bytes())

        # ── Inference ─────────────────────────────────────────────────────────
        t1         = time.time()
        detections = []
        t_infer    = 0.0

        with self._lock:
            loaded     = self._model_loaded
            detector   = self._detector

        if loaded and detector is not None:
            result  = detector.detect(
                frame,
                conf_th=cfg.CONF_THRESHOLD,
                iou_th=cfg.IOU_THRESHOLD,
            )
            t_infer = (time.time() - t1) * 1000

            t2         = time.time()
            frame_area = cfg.INPUT_WIDTH * cfg.INPUT_HEIGHT

            for det in result:
                label = COCO_LABEL_MAP.get(det.class_id, str(det.class_id))
                if label not in RELEVANT_LABELS:
                    continue

                x, y, w, h   = det.x, det.y, det.w, det.h
                area_ratio   = (w * h) / frame_area
                is_danger    = area_ratio > cfg.DANGER_AREA_THRESHOLD
                pos          = position_from_bbox(
                    x, y, w, h, cfg.INPUT_WIDTH, cfg.INPUT_HEIGHT
                )

                detections.append({
                    "label":      label,
                    "confidence": round(det.score, 3),
                    "position":   pos,
                    "is_danger":  is_danger,
                    "bbox":       {"x": x, "y": y, "w": w, "h": h},
                    "area_ratio": round(area_ratio, 4),
                })

            # Suppress flickering phantoms before anything acts on them.
            detections = self._stabilize_detections(detections)

            t_post = (time.time() - t2) * 1000
        else:
            t_post = 0.0

        t_total = (time.time() - t0) * 1000
        latency = {
            "camera_ms":    round(t_cam),
            "inference_ms": round(t_infer),
            "postproc_ms":  round(t_post),
            "total_ms":     round(t_total),
            "fps":          round(1000 / t_total, 1) if t_total > 0 else 0,
        }

        # Send heartbeat so watchdog knows the engine is alive
        if self.orch.watchdog:
            self.orch.watchdog.heartbeat("ai_engine")

        return jpeg, detections, latency

    # ─── Temporal de-flicker ──────────────────────────────────────────────────

    def _stabilize_detections(self, detections: list) -> list:
        """
        Suppress flickering false positives by requiring temporal + spatial
        persistence. A label is only emitted once its best box has stayed in
        roughly the same place for >= detection_min_streak consecutive frames.

        Real objects move smoothly and persist across frames; YOLO phantoms on a
        covered or blurred lens pop in and teleport around, so their streak never
        builds and they're dropped. Set detection_min_streak <= 1 to disable.
        """
        min_streak = int(cfg.get("detection_min_streak", 3))
        if min_streak <= 1:
            return detections

        max_move = float(cfg.get("detection_max_center_move", 0.25))
        w = max(cfg.INPUT_WIDTH, 1)
        h = max(cfg.INPUT_HEIGHT, 1)

        # Keep the highest-confidence box per label for this frame.
        best: dict = {}
        for d in detections:
            lbl = d["label"]
            if lbl not in best or d["confidence"] > best[lbl]["confidence"]:
                best[lbl] = d

        new_track: dict = {}
        stable: list = []
        for lbl, d in best.items():
            b  = d["bbox"]
            cx = (b["x"] + b["w"] / 2) / w
            cy = (b["y"] + b["h"] / 2) / h
            prev = self._track.get(lbl)
            if (prev is not None
                    and abs(cx - prev["cx"]) <= max_move
                    and abs(cy - prev["cy"]) <= max_move):
                streak = prev["streak"] + 1
            else:
                streak = 1
            new_track[lbl] = {"cx": cx, "cy": cy, "streak": streak}
            if streak >= min_streak:
                stable.append(d)

        # Labels missing this frame fall out of new_track → their streak resets.
        self._track = new_track
        return stable

    # ─── Cloud pairing QR scan ─────────────────────────────────────────────────

    def scan_pairing_qr(self):
        """
        Decode a QR from the latest camera frame using the native MaixPy decoder
        (no extra deps, no AI/API key). Throttled. Returns the QR payload string
        if found, else None. Used only while the device is unpaired so the camera
        can be pointed at the pairing QR shown in the web browser.
        """
        now = time.monotonic()
        if now - self._last_qr_scan < 0.6:
            return None
        self._last_qr_scan = now

        frame = self._last_frame
        if frame is None or not MAIX_AVAILABLE:
            return None
        try:
            codes = frame.find_qrcodes()
        except Exception:
            return None
        for qr in codes or []:
            try:
                payload = qr.payload()
            except Exception:
                try:
                    payload = qr.payload   # some MaixPy builds expose it as a property
                except Exception:
                    payload = None
            if isinstance(payload, (bytes, bytearray)):
                payload = payload.decode("utf-8", errors="replace")
            if payload:
                return payload
        return None

    # ─── Cloud triggers ───────────────────────────────────────────────────────

    def _get_adapter(self):
        """Return an adapter instance for the configured ai_provider."""
        return get_adapter(cfg.AI_PROVIDER, cfg)

    def _frame_jpeg(self) -> bytes:
        """Return last-frame JPEG bytes, or empty bytes if unavailable."""
        if self._last_frame is None:
            return b""
        try:
            return bytes(self._last_frame.to_jpeg().to_bytes())
        except Exception:
            return b""

    def _run_with_progress(self, fn, *args, interval_s: float = 3.0):
        """
        Call fn(*args) in the current thread.
        While waiting, queue 'masih_memproses' audio every interval_s seconds
        so user knows the device is still working.
        """
        stop = threading.Event()

        def _progress():
            while not stop.wait(timeout=interval_s):
                self.orch.audio_manager.queue_system("masih_memproses")

        t = threading.Thread(target=_progress, daemon=True)
        t.start()
        try:
            return fn(*args)
        finally:
            stop.set()

    def trigger_scene_description(self):
        """Capture last frame → AI Vision adapter → queue audio description."""
        frame = self._last_frame
        if frame is None:
            self.logger.warn("No frame available for scene description",
                             module="AIEngine")
            return

        self.logger.info(
            f"Sending frame to {cfg.AI_PROVIDER} (scene)", module="AIEngine"
        )
        self.orch.audio_manager.queue_cue("chime_capture.wav")
        self.orch.audio_manager.queue_system("sedang_menganalisis")

        try:
            adapter = self._get_adapter()
            description = self._run_with_progress(
                adapter.describe_scene, self._frame_jpeg(), cfg.PROMPT_SCENE
            )
            self.logger.ok(f"Scene: {description}", module="AIEngine")
            self.orch.audio_manager.queue_cue("chime_success.wav")
            self.orch.audio_manager.queue_info(description)
        except AdapterError as e:
            self.logger.error(f"AI adapter error: {e}", module="AIEngine")
            self.orch.audio_manager.queue_cue("chime_error.wav")
            self.orch.audio_manager.queue_system("gagal_menganalisis")
        except Exception as e:
            self.logger.exception(
                f"Unexpected adapter error: {e}", module="AIEngine", exc=e,
            )
            self.orch.audio_manager.queue_cue("chime_error.wav")
            self.orch.audio_manager.queue_system("gagal_menganalisis")

    def trigger_qris_scan(self):
        """
        QRIS scan dispatcher. Behavior depends on cfg.QRIS_MODE:

          - "offline": local zbar decoder only. No internet required.
                       AI is never called; nominal taken as-is from QR payload.

          - "online":  AI Vision only (legacy behavior). Used when local
                       decoder unavailable or operator explicitly wants
                       AI-only enrichment.

          - "hybrid":  local decode + AI cross-check (default). If local
                       decode succeeds, that's the source of truth for
                       merchant + nominal. AI output is used only to
                       enrich and to flag mismatches; AI nominal can
                       never override the local nominal.
        """
        frame = self._last_frame
        if frame is None:
            return

        mode = cfg.QRIS_MODE
        self.logger.info(
            f"QRIS scan triggered (mode={mode})", module="AIEngine",
        )
        self.orch.audio_manager.queue_cue("chime_capture.wav")
        self.orch.audio_manager.queue_system("memindai_kode_pembayaran")

        jpeg = self._frame_jpeg()

        if mode == "offline":
            self._qris_offline(jpeg)
        elif mode == "online":
            self._qris_online(jpeg)
        else:
            self._qris_hybrid(jpeg)

    # ─── QRIS sub-flows ───────────────────────────────────────────────────────

    def _qris_offline(self, jpeg: bytes):
        try:
            from utils.qris_verify import decode_qris, verify_against_ai, format_audio_message
        except Exception as e:
            self.logger.exception(
                f"QRIS offline decoder unavailable: {e}",
                module="AIEngine", exc=e,
            )
            self.orch.audio_manager.queue_cue("chime_error.wav")
            self.orch.audio_manager.queue_system("gagal_memindai")
            return

        local = decode_qris(jpeg)
        verified = verify_against_ai(local, ai_text="")
        text, safe = format_audio_message(verified, cap=cfg.QRIS_NOMINAL_WARN_CAP)
        self.logger.ok(f"QRIS(offline): {text}", module="AIEngine")
        if safe:
            self.orch.audio_manager.queue_cue("chime_success.wav")
            self.orch.audio_manager.queue_info(text)
        else:
            self.orch.audio_manager.queue_cue("chime_error.wav")
            self.orch.audio_manager.queue_system("gagal_memindai")
        self._save_qris_log(text)

    def _qris_online(self, jpeg: bytes):
        try:
            adapter = self._get_adapter()
            result = self._run_with_progress(adapter.scan_qris, jpeg, cfg.PROMPT_QRIS)
            self.logger.ok(f"QRIS(online): {result}", module="AIEngine")
            self.orch.audio_manager.queue_cue("chime_success.wav")
            self.orch.audio_manager.queue_info(result)
            self._save_qris_log(result)
        except AdapterError as e:
            self.logger.error(f"AI adapter error: {e}", module="AIEngine")
            self.orch.audio_manager.queue_cue("chime_error.wav")
            self.orch.audio_manager.queue_system("gagal_memindai")
        except Exception as e:
            self.logger.exception(
                f"Unexpected adapter error: {e}", module="AIEngine", exc=e,
            )
            self.orch.audio_manager.queue_cue("chime_error.wav")
            self.orch.audio_manager.queue_system("gagal_memindai")

    def _qris_hybrid(self, jpeg: bytes):
        # 1) local decode (fast, offline)
        try:
            from utils.qris_verify import decode_qris, verify_against_ai, format_audio_message
        except Exception as e:
            self.logger.exception(
                f"QRIS hybrid: local decoder unavailable, falling back to online: {e}",
                module="AIEngine", exc=e,
            )
            self._qris_online(jpeg)
            return

        local = decode_qris(jpeg)

        # 2) AI call (best-effort enrichment + nominal cross-check)
        ai_text = ""
        try:
            adapter = self._get_adapter()
            ai_text = self._run_with_progress(adapter.scan_qris, jpeg, cfg.PROMPT_QRIS) or ""
        except AdapterError as e:
            self.logger.warn(
                f"QRIS hybrid: AI unavailable, using local only: {e}",
                module="AIEngine",
            )
        except Exception as e:
            self.logger.exception(
                f"QRIS hybrid AI error: {e}", module="AIEngine", exc=e,
            )

        verified = verify_against_ai(local, ai_text)
        text, safe = format_audio_message(verified, cap=cfg.QRIS_NOMINAL_WARN_CAP)
        self.logger.ok(f"QRIS(hybrid): {text}", module="AIEngine")
        if safe:
            self.orch.audio_manager.queue_cue("chime_success.wav")
            self.orch.audio_manager.queue_info(text)
        else:
            # Local failed AND we have nothing trustworthy → graceful fallback
            if ai_text:
                # Last resort: use raw AI text but flagged in logs
                self.logger.warn(
                    "QRIS hybrid: local failed, falling back to AI raw",
                    module="AIEngine",
                )
                self.orch.audio_manager.queue_cue("chime_success.wav")
                self.orch.audio_manager.queue_info(ai_text)
            else:
                self.orch.audio_manager.queue_cue("chime_error.wav")
                self.orch.audio_manager.queue_system("gagal_memindai")
        self._save_qris_log(text)

    def _save_qris_log(self, result: str):
        import json as _json
        from config import LOG_PATH
        import os

        log_file = os.path.join(LOG_PATH, "qris_log.json")
        os.makedirs(LOG_PATH, exist_ok=True)
        entry = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"), "result": result}
        logs = []
        if os.path.exists(log_file):
            try:
                with open(log_file) as f:
                    logs = _json.load(f)
            except Exception as e:
                self.logger.exception(
                    f"QRIS log read failed: {e}", module="AIEngine", exc=e,
                )
        logs.append(entry)
        with open(log_file, "w") as f:
            _json.dump(logs, f, indent=2, ensure_ascii=False)

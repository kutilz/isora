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
from utils import distance
from utils.logger import position_from_bbox
from utils.stage_timer import StageTimer
from utils.scene_metrics import scene_metrics
from adapters import get_adapter, AdapterError


# Signatures of a *connectivity* failure (DNS / route / timeout / refused) as
# opposed to a server-side or app error. urllib surfaces these inside the
# AdapterError message, e.g. "<urlopen error [Errno -2] Name or service not
# known>" or "<urlopen error timed out>". We use this to speak an honest
# "tidak ada koneksi internet" cue instead of a generic failure. HTTP status
# errors (e.g. "Gemini HTTP 429") intentionally do NOT match — there the network
# is fine, the API just rejected the request.
_NET_ERR_SIGNS = (
    "urlopen error", "getaddrinfo", "name or service not known",
    "temporary failure in name resolution", "timed out", "timeout",
    "connection refused", "network is unreachable", "no route to host",
    "connection reset", "connection aborted", "[errno -2]", "[errno -3]",
)


def _is_network_error(exc) -> bool:
    s = str(exc).lower()
    return any(sign in s for sign in _NET_ERR_SIGNS)


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
        # Last distance tier per label, so distance.band() can apply hysteresis
        # (stops an object on the near/far boundary flapping every frame).
        self._prev_tiers: dict = {}

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
            self._prev_tiers = {}       # and their distance-tier hysteresis state
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
                # is_danger keeps the original global-area rule untouched for
                # back-compat (existing callers/tests depend on this exact
                # field). The new per-class "tier" is the richer signal Lane A's
                # AnnouncePolicy consumes; we intentionally don't redefine
                # is_danger off it here to avoid changing existing behavior.
                is_danger    = area_ratio > cfg.DANGER_AREA_THRESHOLD
                pos          = position_from_bbox(
                    x, y, w, h, cfg.INPUT_WIDTH, cfg.INPUT_HEIGHT
                )
                # Coarse per-class distance tier with ground-contact hint +
                # hysteresis (prev tier for this label stops boundary flapping).
                bbox_bottom_norm = (y + h) / max(cfg.INPUT_HEIGHT, 1)
                tier = distance.band(
                    label, area_ratio, bbox_bottom_norm,
                    prev_tier=self._prev_tiers.get(label), cfg=cfg,
                )
                self._prev_tiers[label] = tier

                detections.append({
                    "label":      label,
                    "confidence": round(det.score, 3),
                    "position":   pos,
                    "is_danger":  is_danger,
                    "tier":       tier,
                    "bbox":       {"x": x, "y": y, "w": w, "h": h},
                    "area_ratio": round(area_ratio, 4),
                })

            # Forget tier-hysteresis state for labels no longer in view, so a
            # returning object starts fresh (mirrors the de-flicker track reset).
            seen = {d["label"] for d in detections}
            self._prev_tiers = {
                lbl: t for lbl, t in self._prev_tiers.items() if lbl in seen
            }

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
        Call fn(*args) in the current thread (the AI loop thread).
        While waiting, every interval_s seconds:
          • queue 'masih_memproses' so the user knows we're still working, and
          • heartbeat the watchdog.

        The heartbeat is essential: fn here blocks the AI loop for the whole
        cloud round-trip (Gemini ~7 s + gTTS warm), during which the loop can't
        send its own heartbeat. Without this, a slow call (>~8 s) makes the
        watchdog reload the engine, and the cvitek camera then fails to reopen
        ("vi get frame timeout") — a hard failure, not just latency.
        """
        stop = threading.Event()

        def _progress():
            # A normal cloud call is ~7 s, so only after it drags past
            # ai_slow_warn_s do we switch the spoken cue from "masih memproses"
            # to "koneksi internet lambat" — by then a slow/flaky network is the
            # likely cause, and saying so is more honest (and reassuring) than a
            # generic "still processing". Threshold stays above the normal call
            # time to avoid false "slow network" alarms on every capture.
            slow_after = float(cfg.get("ai_slow_warn_s", 9.0))
            start = time.monotonic()
            while not stop.wait(timeout=interval_s):
                wd = getattr(self.orch, "watchdog", None)
                if wd:
                    wd.heartbeat("ai_engine")
                elapsed = time.monotonic() - start
                cue = "koneksi_lambat" if elapsed >= slow_after else "masih_memproses"
                self.orch.audio_manager.queue_system(cue)

        t = threading.Thread(target=_progress, daemon=True)
        t.start()
        try:
            return fn(*args)
        finally:
            stop.set()
            # Beat once more on the way out so the loop's next iteration starts
            # with a fresh timer even if the call ran right up to a check.
            wd = getattr(self.orch, "watchdog", None)
            if wd:
                wd.heartbeat("ai_engine")

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
        am = self.orch.audio_manager
        am.queue_cue("chime_capture.wav")
        am.queue_system("sedang_menganalisis")

        try:
            adapter = self._get_adapter()

            # Measure the dominant stage (Gemini round-trip) for the device log.
            # Audio rendering is delegated to AudioManager.speak_scene, which
            # plays from the per-word cache (zero network) when the whole
            # sentence is already cached, else speaks it via gTTS and warms the
            # missing words in the background.
            timer = StageTimer()

            def _work():
                with timer.stage("gemini"):
                    return adapter.describe_scene(self._frame_jpeg(), cfg.PROMPT_SCENE)

            description = self._run_with_progress(_work)
            self.logger.info(f"[scene-timing] {timer.oneline()}", module="AIEngine")
            self.logger.ok(f"Scene: {description}", module="AIEngine")
            am.queue_cue("chime_success.wav")
            # Open a latency record for the /buttons dashboard; speak_scene fills
            # in how the audio was rendered (per-word cache vs whole synth).
            sid = scene_metrics.start_describe(
                description,
                cfg.get("scene_verbosity", "detail"),
                timer.summary().get("gemini_ms", 0),
            )
            am.speak_scene(description, scene_id=sid)
        except AdapterError as e:
            self.logger.error(f"AI adapter error: {e}", module="AIEngine")
            am.queue_cue("chime_error.wav")
            # Distinguish "no internet" from other failures so the user knows
            # whether to check their connection or just retry.
            am.queue_system("tidak_ada_koneksi" if _is_network_error(e)
                            else "gagal_menganalisis")
        except Exception as e:
            self.logger.exception(
                f"Unexpected adapter error: {e}", module="AIEngine", exc=e,
            )
            am.queue_cue("chime_error.wav")
            am.queue_system("tidak_ada_koneksi" if _is_network_error(e)
                            else "gagal_menganalisis")

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

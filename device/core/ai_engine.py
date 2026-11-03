"""
AI Engine — Camera capture, NPU inference, result processing.
Runs inside the AI loop thread.

Resource lifecycle
──────────────────
  release_model()   Free the NPU model (called when switching to context mode).
  reload_model()    Load the model the mode wants — the nav YOLO for explorer,
                    the banknote YOLO for scan bayar — swapping out the other.
  release()         Full teardown: camera + model (called by watchdog restart).
  reload()          Full reinit: camera + model (watchdog restart_fn).
"""

import os
import time
import base64
import threading

try:
    from maix import camera, nn, image
    MAIX_AVAILABLE = True
except ImportError:
    MAIX_AVAILABLE = False

from config import cfg, RELEVANT_LABELS, MUTED_NAV_LABELS, COCO_LABEL_MAP
from utils import diag, distance, orientation
from utils.scene_prompt import scrub_animals
from utils.logger import position_from_bbox
from utils.money import nominal_from_label
from utils.stage_timer import StageTimer
from utils.scene_metrics import scene_metrics
from adapters import get_adapter, AdapterError


# Signatures of a connectivity failure, split by what the user should actually
# DO about it. urllib surfaces these inside the AdapterError message, e.g.
# "<urlopen error [Errno -2] Name or service not known>" or "<urlopen error
# timed out>". HTTP status errors ("OpenAI HTTP 429") intentionally match
# neither — there the network is fine, the API just rejected the request.
#
# The distinction matters: a timeout on a working-but-slow phone hotspot used
# to be announced as "tidak ada koneksi", which is simply false and sends the
# user off to check a connection that was never down. A timeout means the link
# is there and too slow — "koneksi lambat", try again — and only an unreachable
# name/route/port means there is no connection at all.
_NET_DOWN_SIGNS = (
    "getaddrinfo", "name or service not known",
    "temporary failure in name resolution", "connection refused",
    "network is unreachable", "no route to host", "[errno -2]", "[errno -3]",
)
_NET_SLOW_SIGNS = (
    "timed out", "timeout", "connection reset", "connection aborted",
    "incompleteread", "connection broken",
)


# Largest frame handed to MaixPy's QR finder (see AIEngine.read_qr).
_QR_MAX_PIXELS = 320 * 240


def _net_failure_kind(exc):
    """"down" | "slow" | None — which spoken cue this failure has earned."""
    s = str(exc).lower()
    if any(sign in s for sign in _NET_DOWN_SIGNS):
        return "down"
    if any(sign in s for sign in _NET_SLOW_SIGNS):
        return "slow"
    # A bare "urlopen error" with nothing more specific: the request never got
    # a reply, so the honest reading is "the link is not carrying us", which is
    # the slow cue, not a claim that the network is missing.
    return "slow" if "urlopen error" in s else None


def _audio_slot():
    """The speaker's one-clip-at-a-time lock (audio_manager._codec)."""
    from core.audio_manager import _codec
    return _codec()


def _net_failure_cue(exc, fallback: str) -> str:
    kind = _net_failure_kind(exc)
    if kind == "down":
        return "tidak_ada_koneksi"
    if kind == "slow":
        return "koneksi_lambat"
    return fallback


# Past this a call is slower than a normal one (3.5-8 s measured): see what the
# link and the CPU are doing while it is still happening.
_SLOW_CALL_PROBE_S = 9.0


class _ProgressCues:
    """What to say while a cloud call runs, spaced so it does not become noise.

    A clip every 3 s (each about 2 s long) left almost no quiet during a long
    call, and "koneksi internet lambat" repeating did not tell the user anything
    new the second time. Said once per call: a slow call is usually the AI being
    slow, not the connection (measured 3 Nov 2026: 9 and 11 s calls on a healthy
    hotspot). The steady "masih memproses" stays, because a blind user cannot see
    that the device is still alive, but it stays spaced out.
    """

    STILL_WORKING_EVERY_S = 6.0
    AFTER_SLOW_EVERY_S = 9.0
    _JITTER_S = 0.5     # the caller's ticks drift slightly past each 3 s

    def __init__(self, slow_after_s: float):
        self._slow_after_s = slow_after_s
        self._said_slow = False
        self._last = 3.0 - self.STILL_WORKING_EVERY_S   # first cue at the 3 s tick

    def next(self, elapsed: float):
        """The cue for this tick, or None to stay quiet."""
        if elapsed >= self._slow_after_s and not self._said_slow:
            self._said_slow = True
            self._last = elapsed
            return "koneksi_lambat"
        every = self.AFTER_SLOW_EVERY_S if self._said_slow else self.STILL_WORKING_EVERY_S
        if elapsed - self._last >= every - self._JITTER_S:
            self._last = elapsed
            return "masih_memproses"
        return None


class AIEngine:

    _said_slow = False      # did the current cloud call already say "koneksi lambat"?

    # Model spec meaning "the navigation YOLO from cfg.MODEL_PATH". A spec is
    # (path, role); role says what the detections are FOR, which decides who
    # may read them: only "nav" goes through the COCO hazard pipeline in
    # capture_and_infer, only "money" through detect_money.
    NAV = (None, "nav")

    def __init__(self, orchestrator, logger, model=NAV):
        self.orch   = orchestrator
        self.logger = logger

        self._cam:          object = None
        self._detector:     object = None
        self._model_loaded: bool   = False
        self._model_path:   object = None
        self._model_role:   object = None
        self._last_frame:   object = None

        # The model the current mode asked for — what a camera recovery or a
        # watchdog reinit brings back, so neither can swap a scan-bayar engine
        # back to the nav model behind the mode's back. None = no model.
        self._want = model
        # A model that failed to load is not retried every tick: a missing
        # .mud (say, the banknote model not deployed on this unit yet) would
        # otherwise log an error ~15 times a second for as long as the mode
        # stays on. (path, monotonic time of the failure).
        self._failed_model = None
        self._model_retry_s = 30.0
        # RLock, not Lock: release() now holds the lock across release_model()
        # so a model teardown and a camera close can never be split by another
        # thread's reload_model(). Both take the same lock, so it must be
        # re-entrant. See the freeze analysis on _init_model below.
        self._lock = threading.RLock()

        # Gentle camera recovery: when the camera is down, retry at most once
        # per interval instead of letting the watchdog hammer reload() every
        # few seconds (which leaks VI buffers until the C layer segfaults).
        self._last_cam_retry      = 0.0
        self._cam_retry_interval_s = 30.0

        # Throttle for cloud pairing QR scans (only active while unpaired).
        self._last_qr_scan = 0.0
        # Scan bayar's QR-finding model, held NEXT TO the banknote model (both
        # fit: 3.5 + 2.6 MB, ~35 + ~29 ms a frame, measured on isora-810f).
        self._qr_detector = None
        self._qr_failed_at = None

        # Temporal de-flicker tracker. A label must persist in roughly the same
        # spot for several consecutive frames before it counts as a real
        # detection. Kills YOLO phantom boxes that flicker/teleport on a covered
        # or blurred lens (the "keeps announcing a person with the camera
        # covered" failure mode). label -> {"cx", "cy", "streak"}.
        self._track: dict = {}
        # Last distance tier per label, so distance.band() can apply hysteresis
        # (stops an object on the near/far boundary flapping every frame).
        self._prev_tiers: dict = {}

        # Camera orientation (cfg["camera_rotation"], persisted). _rot_software
        # is the residual turn we still have to do ourselves after the sensor
        # ISP took what it could — 0 whenever the hardware handled it all.
        # _orientation_dirty makes a live change from POST /config land on THIS
        # thread at the top of the next frame: every camera call has to stay on
        # the AI loop, never on the HTTP thread mid-read.
        self._rot_software: int  = 0
        self._orientation_dirty  = False

        self._init_camera()
        if model is not None:
            self._init_model(*model)

    # ─── Init helpers ─────────────────────────────────────────────────────────

    def _init_camera(self):
        if not MAIX_AVAILABLE:
            self.logger.warn("MaixPy unavailable — camera skipped", module="AIEngine")
            return
        try:
            # Opening the camera runs MaixPy's multimedia init, and whatever
            # the speaker is playing at that moment is lost — measured: the
            # mode chime on idle → explorer, every time. Take the audio slot
            # for the open: the clip in progress finishes first, the next waits.
            with _audio_slot():
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
            return
        self._apply_orientation()

    # ─── Camera orientation ───────────────────────────────────────────────────

    def request_orientation_reload(self):
        """Ask the AI loop to re-read cfg["camera_rotation"] on its next frame.

        Called from the web thread after POST /config so a mount change takes
        effect immediately — the whole point of the setting is that the helper
        re-clips the device and sees the preview come out the right way up
        without a reboot. The actual camera calls happen on the AI thread.
        """
        self._orientation_dirty = True

    def _apply_orientation(self):
        """Split cfg["camera_rotation"] into a hardware half and a leftover.

        A half turn is exactly hmirror+vflip, which the sensor ISP does for
        free; taking it there keeps the 1-core CPU out of the 30fps frame path
        entirely. Anything the ISP can't do (quarter turns, or a build with no
        mirror/flip accessors) falls through to a software rotate. The explicit
        clear on the non-180 branches matters: a camera object that is still
        carrying a previous session's mirror would otherwise stack with the
        software turn and land on the wrong orientation.
        """
        self._orientation_dirty = False
        rot = cfg.CAMERA_ROTATION
        if self._cam is None:
            self._rot_software = rot
            return
        if rot == 180 and orientation.set_hw_flip(self._cam, True, True):
            self._rot_software = 0
            how = "sensor (hmirror+vflip)"
        else:
            orientation.set_hw_flip(self._cam, False, False)
            self._rot_software = rot
            how = "software" if rot else "sensor"
        if rot:
            self.logger.ok(
                f"Camera rotation: {orientation.rotation_label(rot)} via {how}",
                module="AIEngine",
            )
        else:
            self.logger.info("Camera rotation: normal", module="AIEngine")

    def frame_dims(self) -> tuple:
        """(width, height) of the frame AS THE PIPELINE SEES IT.

        A quarter turn swaps the axes, so every bbox normalization downstream
        (position_from_bbox, area_ratio, the ground-contact hint) has to divide
        by these, not by the configured capture size.
        """
        return orientation.rotated_dims(
            cfg.INPUT_WIDTH, cfg.INPUT_HEIGHT, self._rot_software
        )

    def _init_model(self, path=None, role="nav"):
        """Load the NPU model at `path` (default cfg.MODEL_PATH). HOLDS _lock
        across the allocation.

        The lock is not optional here. The allocation is a .mud parse plus an
        NPU/ION reservation inside a C call, and the same object's release()
        path closes the camera under the same lock. With the allocation left
        outside the lock, a mode press could start a load while the AI thread
        was tearing the engine down: the two C calls interleaved on one core
        and the process wedged, holding the GIL, with nothing left able to run
        (measured in the field — 24 loads against 20 releases over 92 mode
        switches, then a hard freeze).

        The publish of _detector/_model_loaded is under the same lock as the
        reader in capture_and_infer, so a half-constructed detector is never
        visible: previously the two fields could be written in either order
        relative to the reader, leaving explorer mode silently blind.
        """
        if not MAIX_AVAILABLE:
            self.logger.warn("MaixPy unavailable — model skipped", module="AIEngine")
            return
        path = path or cfg.MODEL_PATH
        with self._lock:
            try:
                cls, cls_name  = self._detector_class(path)
                detector       = cls(model=path)
            except Exception as e:
                self._detector     = None
                self._model_loaded = False
                self._model_path   = None
                self._model_role   = None
                self._failed_model = (path, time.monotonic())
                self.logger.error(f"Model load failed ({path}): {e}", module="AIEngine")
                return
            self._detector     = detector
            self._model_loaded = True
            self._model_path   = path
            self._model_role   = role
            self._failed_model = None
            self.logger.ok(f"{cls_name} loaded: {path} ({role})", module="AIEngine")

    @staticmethod
    def _detector_class(model_path):
        """Pick the maix.nn class that matches the .mud and exists in this build.

        Delegates to utils.nn_compat so the benchmark suite shares the choice:
        the benchmarks used to hardcode `nn.YOLO11` and could not start at all on
        a MaixPy 4.5.1 unit (YOLOv5/YOLOv8 only) while the app ran fine on the
        very same image.
        """
        from utils.nn_compat import detector_class
        return detector_class(model_path)

    # ─── Resource management (called by Orchestrator on mode switch) ──────────

    def release_model(self):
        """Unload YOLO from NPU to free memory. Camera stays open.

        Also records that nothing is wanted any more, so a camera recovery in a
        model-less mode (context) does not quietly load one again.
        """
        with self._lock:
            self._want = None
            if self._detector is not None:
                try:
                    del self._detector
                except Exception:
                    pass
                self._detector     = None
                self._model_loaded = False
                self._model_path   = None
                self._model_role   = None
                self.logger.info("YOLO model released (NPU free)", module="AIEngine")

    def reload_model(self, path=None, role="nav"):
        """Make `path` (default cfg.MODEL_PATH) the loaded model. No-op if it
        already is; a different model is released first — the board has room
        for one.

        The check and the load are ONE critical section. Splitting them let two
        callers both see "not loaded" and both allocate, and let a load start
        while release() was closing the camera.
        """
        path = path or cfg.MODEL_PATH
        with self._lock:
            if self._model_loaded and self._model_path == path:
                return
            if self._model_loaded:
                self.release_model()
            self._want = (path, role)
            failed = self._failed_model
            if (failed is not None and failed[0] == path
                    and time.monotonic() - failed[1] < self._model_retry_s):
                return
            self._init_model(path, role)

    def release(self):
        """Full teardown — camera + model. Called before watchdog restart.

        One lock span for the whole teardown: a reload_model() arriving from a
        button thread mid-release used to slip between the model drop and the
        camera close and allocate into an engine the orchestrator had already
        let go of — an NPU allocation nobody held a reference to, leaked until
        reboot. On a 128MB swapless board that leak is what turned a survivable
        mode-mash into a probabilistic hard freeze.
        """
        with self._lock:
            self.release_model()
            self.release_qr_detector()
            if self._cam is not None:
                try:
                    with _audio_slot():      # mmf teardown, see _init_camera
                        self._cam.close()
                except Exception:
                    pass
                self._cam = None

    def reload(self):
        """Full reinit after a crash. Used as watchdog restart_fn."""
        self.logger.warn("Reloading AI Engine (watchdog triggered)", module="AIEngine")
        want = self._want              # release() clears it
        self.release()
        time.sleep(0.5)
        self._init_camera()
        if want is not None:
            self._want = want
            self._init_model(*want)

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
        if self._cam is not None and not self._model_loaded and self._want is not None:
            self._init_model(*self._want)

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

        # Pick up a live camera_rotation change (POST /config) here, on the AI
        # thread, before the read — never from the HTTP thread mid-frame.
        if self._orientation_dirty:
            self._apply_orientation()

        # ── Camera read with single auto-recover ──────────────────────────────
        try:
            frame = self._cam.read()
        except RuntimeError as e:
            self.logger.warn(f"Camera read error ({e}) — attempting reopen",
                             module="AIEngine")
            try:
                with _audio_slot():          # see _init_camera
                    self._cam.close()
            except Exception:
                pass
            time.sleep(0.3)
            try:
                with _audio_slot():
                    self._cam.open()
                # A reopened sensor comes back with its ISP defaults, so the
                # hardware half turn is gone. Without this, a device mounted
                # upside down quietly rights itself after any camera hiccup —
                # and every spoken "kiri"/"kanan" inverts with it.
                self._apply_orientation()
                frame = self._cam.read()
                self.logger.ok("Camera recovered", module="AIEngine")
            except Exception as e2:
                self.logger.error(f"Camera reopen failed: {e2}", module="AIEngine")
                return None, [], {}

        # Orientation correction happens HERE — before the snapshot, before
        # inference, before the QR decode — so every consumer (web preview,
        # YOLO, position/distance math, pairing scan) sees one frame the right
        # way up. 0 returns the same object, so the common case costs nothing.
        if self._rot_software:
            frame = orientation.rotate_image(frame, self._rot_software)

        t_cam = (time.time() - t0) * 1000
        self._last_frame = frame

        # ── Dashboard preview (only when it is actually wanted) ───────────────
        # to_jpeg() is ~17 ms of an ~18 ms tick on this SoC — by far the most
        # expensive thing here after inference — and for most of the device's
        # life nobody has the page open. The orchestrator says whether anyone
        # asked recently AND whether the thermal budget still allows it.
        # Cloud captures (describe / QRIS) encode _last_frame on demand in
        # _frame_jpeg(), so they are unaffected.
        jpeg = None
        if self.orch.wants_preview():
            jpeg = frame.to_jpeg()
            self.orch.snapshot = bytes(jpeg.to_bytes())
        elif self.orch.snapshot is not None:
            # Drop the old frame rather than serving one from hours ago: a
            # stale preview is worse than none, because it looks live.
            self.orch.snapshot = None

        # ── Inference ─────────────────────────────────────────────────────────
        t1         = time.time()
        detections = []
        t_infer    = 0.0

        with self._lock:
            loaded     = self._model_loaded and self._model_role == "nav"
            detector   = self._detector

        # Only the nav model's classes are COCO ids. With the banknote model on
        # the NPU (scan bayar) this is just the camera read; detect_money()
        # runs that model when the mode asks for it.
        if loaded and detector is not None:
            result  = detector.detect(
                frame,
                conf_th=cfg.CONF_THRESHOLD,
                iou_th=cfg.IOU_THRESHOLD,
            )
            t_infer = (time.time() - t1) * 1000

            t2         = time.time()
            frame_w, frame_h = self.frame_dims()
            frame_area = frame_w * frame_h

            for det in result:
                label = COCO_LABEL_MAP.get(det.class_id, str(det.class_id))
                if label not in RELEVANT_LABELS or label in MUTED_NAV_LABELS:
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
                    x, y, w, h, frame_w, frame_h
                )
                # Coarse per-class distance tier with ground-contact hint +
                # hysteresis (prev tier for this label stops boundary flapping).
                bbox_bottom_norm = (y + h) / max(frame_h, 1)
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
        # Effective (post-rotation) frame size: a quarter turn swaps the axes,
        # and normalizing the box centre by the wrong one would distort the
        # per-frame movement test that decides what counts as a phantom.
        _fw, _fh = self.frame_dims()
        w = max(_fw, 1)
        h = max(_fh, 1)

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
        return self.read_qr()

    def read_qr(self):
        """Payload of the first QR in the latest frame (native MaixPy decoder,
        no network), or None. Unthrottled: scan bayar paces it itself."""
        frame = self._last_frame
        if frame is None or not MAIX_AVAILABLE:
            return None
        found = self._decode_qr(frame)
        return found[0] if found else None

    def _decode_qr(self, frame):
        """(payload, cx, cy, size) of the first readable QR in `frame`, or None.
        Position as 0..1 of the frame, size over its shorter side."""
        try:
            # MaixPy's QR finder runs out of its fast frame-buffer stack on a
            # big image and then SEGFAULTS the whole app (measured on a 1280-px
            # frame) — no exception reaches Python. Camera frames are 320x224,
            # so this costs nothing normally; it only matters if
            # input_width/height were ever raised.
            w, h = frame.width(), frame.height()
            if w * h > _QR_MAX_PIXELS:
                s = (_QR_MAX_PIXELS / float(w * h)) ** 0.5
                frame = frame.resize(max(int(w * s), 1), max(int(h * s), 1))
                w, h = frame.width(), frame.height()
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
            if not payload:
                continue
            try:
                x, y, qw, qh = qr.x(), qr.y(), qr.w(), qr.h()
                return (payload, (x + qw / 2.0) / w, (y + qh / 2.0) / h,
                        max(qw, qh) / float(min(w, h)))
            except Exception:
                return (payload, 0.5, 0.5, 1.0)     # read, position unknown
        return None

    def locate_qr(self):
        """Where a QR is right now, as a qr_guide.Sighting, or None. No network.

        A code that can be read says exactly what and where. One still too far to
        read is found from its finder squares, which survive at about a third of
        the size the decoder needs — the difference between being told "kode di
        kanan" from a step away and only from arm's length.
        """
        from utils.qr_guide import Sighting, locate_finders
        frame = self._qr_frame()
        if frame is None or not MAIX_AVAILABLE:
            return None
        with self._lock:
            detector = self._qr_detector
        if detector is not None:
            # The model finds a code as an object from ~30 px wide, where the
            # decoder and the finder-square search both see nothing. It says
            # where; decoding (exact, and what says "QRIS, merchant X") is only
            # attempted once the code is big enough to have a chance.
            try:
                objs = detector.detect(frame, conf_th=float(cfg.get("qr_conf_threshold", 0.4)),
                                       iou_th=0.45)
            except Exception as e:
                self.logger.warn(f"QR model failed: {e}", module="AIEngine")
                objs = None
            if not objs:
                return None
            o = max(objs, key=lambda o: o.score)
            w, h = float(frame.width()), float(frame.height())
            sighting = Sighting((o.x + o.w / 2.0) / w, (o.y + o.h / 2.0) / h,
                                max(o.w, o.h) / min(w, h))
            if sighting.size >= 0.18:
                found = self._decode_qr(frame)
                if found:
                    sighting.payload = found[0]
            return sighting
        found = self._decode_qr(frame)
        if found:
            payload, cx, cy, size = found
            return Sighting(cx, cy, size, payload)
        try:
            gray = frame.to_format(image.Format.FMT_GRAYSCALE)
            return locate_finders(bytes(gray.to_bytes()), gray.width(), gray.height())
        except Exception as e:
            self.logger.warn(f"QR locate failed: {e}", module="AIEngine")
            return None

    def ensure_qr_detector(self):
        """Load the QR-finding model if it is not loaded. AI-LOOP THREAD.
        A unit without the file keeps the finder-square search."""
        path = cfg.get("qr_model_path", "")
        if not path or not MAIX_AVAILABLE or self._qr_detector is not None:
            return
        if self._qr_failed_at is not None and time.monotonic() - self._qr_failed_at < 60:
            return
        if not os.path.exists(path):
            self._qr_failed_at = time.monotonic()
            self.logger.warn(f"QR model missing: {path}", module="AIEngine")
            return
        with self._lock:
            try:
                cls, _name = self._detector_class(path)
                self._qr_detector = cls(model=path)
                self.logger.ok(f"QR model loaded: {path}", module="AIEngine")
            except Exception as e:
                self._qr_detector = None
                self._qr_failed_at = time.monotonic()
                self.logger.error(f"QR model load failed ({path}): {e}", module="AIEngine")

    def release_qr_detector(self):
        with self._lock:
            if self._qr_detector is None:
                return
            try:
                del self._qr_detector
            except Exception:
                pass
            self._qr_detector = None
            self.logger.info("QR model released", module="AIEngine")

    def _qr_frame(self):
        """The frame to look for a code in."""
        return self._last_frame

    def save_guide_photo(self, cue: str):
        """Keep the frame behind a spoken direction with what was said, so a
        session can be reviewed afterwards (cfg debug_save_frames)."""
        if not cfg.get("debug_save_frames", False):
            return
        name = diag.save_frame(self._frame_jpeg(), cfg, "panduan_qr")
        diag.frame_result(name, cue)

    # ─── Scan bayar: banknotes ────────────────────────────────────────────────

    def detect_money(self) -> list:
        """Run the banknote model on the latest frame.

        Returns [] unless the banknote model is the one on the NPU (the mode
        swaps it in through reload_model). Each hit carries `nominal` — the
        rupiah value parsed from the .mud label — next to the usual dashboard
        fields, so the web preview can draw it like any other detection.
        """
        with self._lock:
            detector = self._detector if self._model_role == "money" else None
        frame = self._last_frame
        if detector is None or frame is None:
            return []
        objs = detector.detect(
            frame,
            conf_th=float(cfg.get("money_conf_threshold", 0.5)),
            iou_th=cfg.IOU_THRESHOLD,
        )
        labels = list(getattr(detector, "labels", None) or [])
        frame_w, frame_h = self.frame_dims()
        frame_area = max(frame_w * frame_h, 1)
        out = []
        for o in objs:
            label = (labels[o.class_id] if 0 <= o.class_id < len(labels)
                     else str(o.class_id)).strip()
            out.append({
                "label":      label,
                "nominal":    nominal_from_label(label),
                "confidence": round(o.score, 3),
                "position":   position_from_bbox(o.x, o.y, o.w, o.h, frame_w, frame_h),
                "is_danger":  False,
                "tier":       "far",
                "bbox":       {"x": o.x, "y": o.y, "w": o.w, "h": o.h},
                "area_ratio": round((o.w * o.h) / frame_area, 4),
            })
        if self.orch.watchdog:
            self.orch.watchdog.heartbeat("ai_engine")
        return out

    # ─── Cloud triggers ───────────────────────────────────────────────────────

    def _get_adapter(self):
        """Return an adapter instance for the configured ai_provider."""
        return get_adapter(cfg.AI_PROVIDER, cfg)

    def grab_fresh_frame(self) -> bool:
        """Read the camera now so _last_frame shows the scene at this moment.

        For modes that do not read every tick (context). The sensor keeps
        streaming into the VI buffers while nobody reads, so the first read can
        hand back a frame queued earlier — it is read and thrown away.
        """
        self.capture_and_infer()
        self.capture_and_infer()
        return self._last_frame is not None

    def _frame_jpeg(self) -> bytes:
        """Return last-frame JPEG bytes, or empty bytes if unavailable."""
        if self._last_frame is None:
            return b""
        try:
            return bytes(self._last_frame.to_jpeg().to_bytes())
        except Exception:
            return b""

    def _failure_cue(self, exc, fallback: str) -> str:
        """Like _net_failure_cue, but a timeout right after the wait already said
        "koneksi lambat" must not say it again: that sounds like more waiting,
        when in fact this attempt is over and the user should press again."""
        cue = _net_failure_cue(exc, fallback)
        return fallback if cue == "koneksi_lambat" and self._said_slow else cue

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
        self._said_slow = False

        def _progress():
            cues = _ProgressCues(float(cfg.get("ai_slow_warn_s", 12.0)))
            start = time.monotonic()
            probed = False
            while not stop.wait(timeout=interval_s):
                wd = getattr(self.orch, "watchdog", None)
                if wd:
                    wd.heartbeat("ai_engine")
                elapsed = time.monotonic() - start
                if not probed and elapsed >= _SLOW_CALL_PROBE_S:
                    probed = True
                    diag.net_probe("ai_slow")
                cue = cues.next(elapsed)
                if cue == "koneksi_lambat":
                    self._said_slow = True
                if cue:
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
        photo = ""

        try:
            adapter = self._get_adapter()

            # Measure the dominant stage (AI vision round-trip) for the device
            # log. Tagged with the active provider so [scene-timing]
            # dominant=... reflects whichever one actually ran (openai/gemini/
            # claude), not a stale "gemini" label from when that was the only
            # option. Audio rendering is delegated to AudioManager.speak_scene,
            # which plays from the per-word cache (zero network) when the
            # whole sentence is already cached, else speaks it via gTTS and
            # warms the missing words in the background.
            timer = StageTimer()
            provider = cfg.AI_PROVIDER

            def _work():
                nonlocal photo
                with timer.stage(provider):
                    jpeg = self._frame_jpeg()
                    photo = diag.save_frame(jpeg, cfg, "konteks")
                    return adapter.describe_scene(jpeg, cfg.PROMPT_SCENE)

            description = self._run_with_progress(_work)
            diag.frame_result(photo, description)
            self.logger.info(f"[scene-timing] {timer.oneline()}", module="AIEngine")
            scrubbed = scrub_animals(description)
            if scrubbed != description:
                self.logger.info(f"Animal word replaced in: {description}", module="AIEngine")
                description = scrubbed
            self.logger.ok(f"Scene: {description}", module="AIEngine")
            am.queue_cue("chime_success.wav")
            # Open a latency record for the /buttons dashboard; speak_scene fills
            # in how the audio was rendered (per-word cache vs whole synth).
            # scene_metrics still stores this under its historical "gemini_ms"
            # key regardless of provider (dashboard/tests key off that name).
            sid = scene_metrics.start_describe(
                description,
                cfg.get("scene_verbosity", "detail"),
                timer.summary().get(f"{provider}_ms", 0),
            )
            am.speak_scene(description, scene_id=sid)
        except AdapterError as e:
            diag.frame_result(photo, e, ok=False)
            self.logger.error(f"AI adapter error: {e}", module="AIEngine")
            am.queue_cue("chime_error.wav")
            # Say which of the three it actually was — no connection, a
            # connection too slow to finish in time, or a failure on the far
            # end — so the user knows whether to move, wait, or just retry.
            am.queue_system(self._failure_cue(e, "gagal_menganalisis"))
            self._offline_fallback()
        except Exception as e:
            diag.frame_result(photo, e, ok=False)
            self.logger.exception(
                f"Unexpected adapter error: {e}", module="AIEngine", exc=e,
            )
            am.queue_cue("chime_error.wav")
            am.queue_system(self._failure_cue(e, "gagal_menganalisis"))
            self._offline_fallback()

    def _offline_fallback(self) -> int:
        """Mode PIMNAS: after a failed describe, say what the nav YOLO sees.

        Real detections from a fresh frame, spoken from the pre-recorded nav
        phrases ("orang di depan") — no network, and nothing that was not
        actually in front of the camera. Returns how many objects were read
        out. Off outside the event profile, where the failure cue alone stays
        the behaviour a daily user knows.
        """
        if not cfg.EVENT_MODE:
            return 0
        with self._lock:
            ready = self._model_loaded and self._model_role == "nav"
        if not ready:
            return 0
        try:
            detections = []
            # The first read can be a frame queued while nobody was reading.
            for _ in range(2):
                _, detections, _ = self.capture_and_infer()
            if not detections:
                return 0
            self.logger.info(
                f"Offline fallback: {len(detections)} object(s)",
                module="AIEngine")
            self.orch.audio_manager.announce_detections(detections, force=True)
            return len(detections)
        except Exception as e:
            self.logger.warn(f"Offline fallback failed: {e}", module="AIEngine")
            return 0

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
        self._qris_photo = diag.save_frame(jpeg, cfg, "qris")

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
            # Same distinction as a scene describe: "gagal memindai" tells the
            # user to re-aim at the QR when the real problem was the link.
            self.orch.audio_manager.queue_system(
                self._failure_cue(e, "gagal_memindai"))
        except Exception as e:
            self.logger.exception(
                f"Unexpected adapter error: {e}", module="AIEngine", exc=e,
            )
            self.orch.audio_manager.queue_cue("chime_error.wav")
            self.orch.audio_manager.queue_system(
                self._failure_cue(e, "gagal_memindai"))

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
                # Last resort: the AI's reading. A vision model cannot decode a
                # QR — it reads the printed sticker, and may guess — so this is
                # never presented as a scan result: no success chime, and the
                # user is told to confirm with the cashier before paying.
                self.logger.warn(
                    "QRIS hybrid: local failed, falling back to AI raw",
                    module="AIEngine",
                )
                self.orch.audio_manager.queue_cue("chime_error.wav")
                guess = ai_text.strip().rstrip(".")
                self.orch.audio_manager.queue_info(
                    f"QR tidak terbaca. Perkiraan AI, belum pasti: {guess}. "
                    "Mohon pastikan nominal ke kasir.")
                text = f"(AI, belum terverifikasi) {guess}"
            else:
                self.orch.audio_manager.queue_cue("chime_error.wav")
                self.orch.audio_manager.queue_system("gagal_memindai")
        self._save_qris_log(text)

    # Enough history to look back over a day of use. The file is read whole and
    # rewritten on every scan, so an unbounded one made each payment scan
    # slower than the last.
    _QRIS_LOG_MAX = 200

    def _save_qris_log(self, result: str):
        """Append to qris_log.json. Bounded, atomic, and never raises: the
        scan result has already been spoken, and a full or read-only SD card
        must not turn that into an error in the AI loop."""
        diag.frame_result(getattr(self, "_qris_photo", ""), result)
        import json as _json
        from config import LOG_PATH
        import os

        try:
            log_file = os.path.join(LOG_PATH, "qris_log.json")
            os.makedirs(LOG_PATH, exist_ok=True)
            entry = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"), "result": result}
            logs = []
            if os.path.exists(log_file):
                try:
                    with open(log_file) as f:
                        logs = _json.load(f)
                    if not isinstance(logs, list):
                        logs = []
                except Exception as e:
                    self.logger.warn(f"QRIS log unreadable, starting over: {e}",
                                     module="AIEngine")
                    logs = []
            logs.append(entry)
            logs = logs[-self._QRIS_LOG_MAX:]
            # tmp + replace: a power cut mid-write leaves the old file, not a
            # truncated one that the next scan would throw away.
            tmp = log_file + ".tmp"
            with open(tmp, "w") as f:
                _json.dump(logs, f, indent=2, ensure_ascii=False)
            os.replace(tmp, log_file)
        except Exception as e:
            self.logger.warn(f"QRIS log not saved: {e}", module="AIEngine")

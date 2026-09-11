"""
Orchestrator — Event-driven state machine & shared state hub.

Mode transitions
────────────────
  switch_mode(new_mode)   Thread-safe; releases resources from the old mode,
                          loads resources for the new one, plays a confirmation
                          audio cue. Can be called from any thread.

Hardware button
───────────────
  If cfg.BUTTON_PIN_MODE >= 0, a dedicated thread monitors that GPIO pin and
  cycles through modes on each falling edge (press). Configure the pin number
  in /root/config.json ("button_pin_mode": <N>).

Watchdog
────────
  The Orchestrator exposes self.watchdog so the AI Engine can send heartbeats.
  Set by main.py after creation via orch.watchdog = wd.

Thermal throttling
──────────────────
  HealthMonitor calls _on_thermal_throttle / _on_thermal_recover which adjust
  the effective camera FPS by writing to cfg at runtime.
"""

import queue
import threading
import time
from typing import Optional

from config import cfg


class Orchestrator:

    MODES = ("explorer", "context", "qris")
    # Button press cycles through modes in this order
    _MODE_CYCLE = {"explorer": "context", "context": "qris", "qris": "explorer"}

    # Modes that keep YOLO loaded
    _YOLO_MODES = {"explorer"}

    def __init__(self, logger):
        self.logger = logger

        # ── Shared state ──────────────────────────────────────────────────────
        self._lock = threading.Lock()

        self._mode      = "explorer"
        self._ai_focus  = False
        self._ai_focus_until = 0.0

        self._detections  = []
        self._snapshot_bytes: Optional[bytes] = None
        self._latency = {
            "camera_ms": 0, "inference_ms": 0,
            "postproc_ms": 0, "total_ms": 0, "fps": 0.0,
        }

        self._pending_command = None
        self._running         = True

        # Detection-audio mute: monotonic deadline until which explorer-mode
        # detection alerts stay silent, so a user action's audio (mode
        # confirmation / description / repeat) isn't drowned by the spam right
        # after they interact. Set via note_user_interaction(); read by the
        # explorer tick through detection_audio_suppressed().
        self._suppress_det_until = 0.0

        # ── Module references (set after init) ────────────────────────────────
        self.ai_engine:    object = None
        self.audio_manager: object = None
        self.watchdog:      object = None   # set by main.py
        self.onboarding:    object = None   # set by main.py (spoken-URL onboarding)
        self.mdns:          object = None   # set by main.py (mDNS publisher)
        self.data_collector: object = None  # set by main.py (Mode Ambil Data)

        # ── Mode-change event (wakes AI loop when mode switches) ──────────────
        self._mode_event = threading.Event()

        # ── Mode Ambil Data: set once the AI loop has released the aural camera
        # and the device is idling in collection mode (camera free for capture).
        self._collection_ready = threading.Event()

        # ── Hardware buttons (MODE + ACTION) ─────────────────────────────────────
        mode_pin = self._button_pin()
        if mode_pin:
            self._start_button_listener(mode_pin, self._on_button)
        action_pin = self._action_pin()
        if action_pin:
            self._start_button_listener(action_pin, self._on_action_button)

        # ── Simulated buttons (web fallback for dead hardware buttons) ───────────
        # The companion web page can inject MODE/ACTION presses when the physical
        # buttons are broken. Presses are handled on a dedicated worker thread —
        # exactly like the GPIO BtnListener — so the HTTP handler never blocks and
        # presses stay serialized (no concurrent switch_mode / model-reload races).
        # Bounded queue: a flood of taps is dropped, never piled up → no backlog.
        self._sim_btn_q: "queue.Queue" = queue.Queue(maxsize=8)
        threading.Thread(
            target=self._sim_button_worker, daemon=True, name="SimBtn"
        ).start()

    # ─── Thread-safe properties ───────────────────────────────────────────────

    @property
    def mode(self) -> str:
        with self._lock:
            return self._mode

    @property
    def ai_focus(self) -> bool:
        with self._lock:
            if self._ai_focus and time.time() > self._ai_focus_until:
                self._ai_focus = False
            return self._ai_focus

    def activate_ai_focus(self, duration: Optional[float] = None):
        d = duration or cfg.AI_FOCUS_DURATION_S
        with self._lock:
            self._ai_focus       = True
            self._ai_focus_until = time.time() + d
        self.logger.info(f"AI Focus active for {d}s", module="Orchestrator")

    @property
    def detections(self) -> list:
        with self._lock:
            return list(self._detections)

    @detections.setter
    def detections(self, value: list):
        with self._lock:
            self._detections = value

    @property
    def snapshot(self) -> Optional[bytes]:
        with self._lock:
            return self._snapshot_bytes

    @snapshot.setter
    def snapshot(self, value: bytes):
        with self._lock:
            self._snapshot_bytes = value

    @property
    def latency(self) -> dict:
        with self._lock:
            return dict(self._latency)

    @latency.setter
    def latency(self, value: dict):
        with self._lock:
            self._latency.update(value)

    # ─── Audio (delegates to AudioManager) ───────────────────────────────────

    def enqueue_audio(self, text: str):
        """Low-priority audio — wraps audio_manager.queue_info for compat."""
        if self.audio_manager:
            self.audio_manager.queue_info(text)

    def pop_audio(self):
        """Legacy stub for web_server.py — audio now plays on-device directly."""
        return None

    # ─── Command queue (from Web UI) ─────────────────────────────────────────

    def set_pending_command(self, cmd: str, data: dict = None):
        with self._lock:
            self._pending_command = {"cmd": cmd, "data": data or {}}

    def pop_pending_command(self) -> Optional[dict]:
        with self._lock:
            cmd = self._pending_command
            self._pending_command = None
            return cmd

    # ─── Status snapshot ──────────────────────────────────────────────────────

    def get_status(self) -> dict:
        audio_text = ""
        last_caption = {"text": "", "time_iso": "", "priority": "low"}
        if self.audio_manager:
            try:
                audio_text = self.audio_manager.current_text
            except Exception:
                pass
            try:
                last_caption = self.audio_manager.last_caption
            except Exception:
                pass

        # ── Hardware telemetry for companion dashboard (handoff §8.1) ─────────
        battery = self._battery_pct()
        wifi    = self._wifi_info()
        temp_c  = self._cpu_temp_c()

        # ── Device identity (multi-device safe) ───────────────────────────────
        dev_id = dev_name = dev_host = ""
        try:
            from utils import identity as _idy
            dev_id   = _idy.device_id()
            dev_name = _idy.device_name()
            dev_host = _idy.mdns_hostname()
        except Exception:
            pass

        # Data-collection snapshot (cheap attribute reads; DataCollector has its
        # own lock for the heavy stats, so we avoid calling it under our lock).
        dc = self.data_collector
        dc_running = bool(getattr(dc, "is_running", False)) if dc else False
        dc_count   = getattr(dc, "capture_count", 0) if dc else 0

        # ── Context-mode latency + per-word cache state (/buttons dashboard) ───
        try:
            from utils.scene_metrics import scene_metrics as _sm
            scene_metrics = _sm.snapshot()
        except Exception:
            scene_metrics = {"last": None, "summary": {"count": 0}, "history": []}
        cached_words_total = 0
        if self.audio_manager is not None:
            try:
                cached_words_total = self.audio_manager.cached_words_count()
            except Exception:
                pass

        with self._lock:
            return {
                "mode":         self._mode,
                "device_id":    dev_id,
                "device_name":  dev_name,
                "mdns_host":    dev_host,
                "url_ack":      cfg.get("url_ack", False),
                "ai_focus":     self._ai_focus,
                "detections":   list(self._detections),
                "latency":      dict(self._latency),
                "audio_text":   audio_text,
                "audio_mode":   cfg.get("audio_mode", "both"),
                "scene_verbosity": cfg.get("scene_verbosity", "detail"),
                # Per-word audio cache: "caching per-kata" (True) vs "satu blok
                # audio" (False), the inter-word gap (ms; <0 = overlap), the
                # number of warmed words, and recent describe latency.
                "word_cache_enabled": bool(cfg.get("word_cache_enabled", True)),
                "word_cache_gap_ms":  int(cfg.get("word_cache_gap_ms", -10)),
                "cached_words_total": cached_words_total,
                "scene_metrics":      scene_metrics,
                "last_caption": last_caption,
                "battery":      battery,
                "wifi_signal":  wifi["signal"],
                "wifi_ssid":    wifi["ssid"],
                "temperature":  temp_c,
                "setup_completed": cfg.get("setup_completed", False),
                "cam_w":        cfg.get("input_width",  320),
                "cam_h":        cfg.get("input_height", 224),
                # Mode Ambil Data — surfaced to the dashboard + cloud heartbeat
                # so the mode and capture progress are diagnosable remotely.
                "data_collection_mode": cfg.get("data_collection_mode", False),
                "capturing":    bool(dc_running),
                "capture_count": int(dc_count),
            }

    # ─── Hardware telemetry helpers (called from get_status) ──────────────────

    def _battery_pct(self):
        """
        Return battery percentage 0..100 if I2C HAT enabled & gauge readable,
        else None. UI shows "(belum dikalibrasi)" when None.
        """
        try:
            from utils.health import battery_hat_present, battery_info
            if not battery_hat_present():
                return None
            info = battery_info()
            # Stub returns {"present": True}; once HAT driver lands it
            # should also return "percent": int.
            if "percent" in info:
                return int(info["percent"])
            return None
        except Exception:
            return None

    @staticmethod
    def _wifi_info() -> dict:
        """
        Read SSID + signal bars (0..4) from /proc/net/wireless and iwconfig.
        Cheap (no shell-out unless iwconfig is needed for SSID lookup).
        Falls back gracefully to {"ssid": "", "signal": 0} on any error.
        """
        ssid = ""
        signal = 0
        # 1. Signal bars from /proc/net/wireless quality column.
        try:
            with open("/proc/net/wireless") as f:
                lines = f.read().splitlines()
            for raw in lines[2:]:
                parts = raw.split()
                if not parts:
                    continue
                # quality.link is parts[2], e.g. "70." — typical range 0..70.
                q_raw = parts[2].rstrip(".")
                try:
                    q = float(q_raw)
                except ValueError:
                    continue
                # Map 0..70 → 0..4 bars (every ~17.5).
                signal = max(0, min(4, int(q / 17.5)))
                break
        except Exception:
            pass
        # 1b. Fallback signal via `iw dev wlan0 link` (parses "signal: -NN dBm").
        #     Used on devices where /proc/net/wireless is absent (e.g. MaixCAM
        #     with AIC8800 driver that doesn't populate that file).
        if signal == 0:
            import subprocess as _sp
            try:
                _iw = _sp.run(
                    ["/usr/sbin/iw", "dev", "wlan0", "link"],
                    shell=False, stdin=_sp.DEVNULL,
                    stdout=_sp.PIPE, stderr=_sp.DEVNULL,
                    timeout=1,
                )
                for _line in _iw.stdout.decode("utf-8", "ignore").splitlines():
                    _line = _line.strip()
                    if _line.startswith("signal:"):
                        # "signal: -62 dBm" → -62
                        try:
                            _dbm = float(_line.split()[1])
                            # dBm → 0..4 bars: -50→4, -60→3, -70→2, -80→1, <-80→0
                            if _dbm >= -50:
                                signal = 4
                            elif _dbm >= -60:
                                signal = 3
                            elif _dbm >= -70:
                                signal = 2
                            elif _dbm >= -80:
                                signal = 1
                            else:
                                signal = 0
                        except (ValueError, IndexError):
                            pass
                        break
            except Exception:
                pass
        # 2. SSID — try iwgetid (full path for non-login shells where
        #    /usr/sbin is absent from PATH), then fall back to wpa_cli.
        import subprocess
        for cmd in (
            ["/usr/sbin/iwgetid", "-r"],
            ["iwgetid", "-r"],
        ):
            try:
                out = subprocess.run(
                    cmd,
                    shell=False, stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    timeout=1,
                )
                if out.returncode == 0:
                    ssid = out.stdout.decode("utf-8", "ignore").strip()
                    if ssid:
                        break
            except (FileNotFoundError, Exception):
                pass
        if not ssid:
            # Fallback: wpa_cli status (parses "ssid=..." line)
            try:
                out2 = subprocess.run(
                    ["wpa_cli", "-i", "wlan0", "status"],
                    shell=False, stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    timeout=1,
                )
                if out2.returncode == 0:
                    for line in out2.stdout.decode("utf-8", "ignore").splitlines():
                        if line.startswith("ssid="):
                            ssid = line[5:].strip()
                            break
            except Exception:
                pass
        return {"ssid": ssid, "signal": signal}

    @staticmethod
    def _cpu_temp_c():
        """Return CPU temperature in °C, or None if unavailable."""
        try:
            from utils.health import _thermals
            t = _thermals()
            if not t:
                return None
            return max(t.values())
        except Exception:
            return None

    # ─── Mode switching ───────────────────────────────────────────────────────

    def switch_mode(self, new_mode: str):
        """
        Thread-safe mode switch.
        1. Validates the new mode.
        2. Releases resources from the old mode.
        3. Updates internal state.
        4. Loads resources for the new mode.
        5. Plays a confirmation cue.
        """
        if new_mode not in self.MODES:
            self.logger.warn(f"Unknown mode: {new_mode}", module="Orchestrator")
            return

        with self._lock:
            if self._mode == new_mode:
                return
            old_mode   = self._mode
            self._mode = new_mode

        self.logger.info(
            f"Mode: {old_mode} → {new_mode}",
            module="Orchestrator",
            transition=f"{old_mode}→{new_mode}",
        )

        # Release NPU model when leaving explorer mode
        if old_mode in self._YOLO_MODES and new_mode not in self._YOLO_MODES:
            if self.ai_engine:
                self.ai_engine.release_model()

        # Reload NPU model when returning to explorer mode
        if new_mode in self._YOLO_MODES and old_mode not in self._YOLO_MODES:
            if self.ai_engine:
                self.ai_engine.reload_model()

        # Wake up the AI loop so it picks up the new mode immediately
        self._mode_event.set()

        # Mute detection alerts briefly so the mode confirmation is heard, not
        # drowned by spam (a mode switch is always a deliberate user action).
        self.note_user_interaction()
        if self.audio_manager:
            self.audio_manager.queue_cue("chime_mode.wav")
            self.audio_manager.queue_system(f"mode_{new_mode}")

    # ─── Hardware button listener ─────────────────────────────────────────────

    @staticmethod
    def _pin_name(key):
        """Resolve a button-pad config value to a pad name (e.g. 'A14') or None."""
        raw = cfg.get(key, -1)
        if raw in (-1, "-1", "", None):
            return None
        if isinstance(raw, int):
            return f"A{raw}"          # legacy numeric config → CVITEK pad name
        return str(raw).strip() or None

    def _button_pin(self):
        """MODE button pad name, or None when disabled."""
        return self._pin_name("button_pin_mode")

    def _action_pin(self):
        """ACTION button pad name, or None when disabled."""
        return self._pin_name("button_pin_action")

    def _start_button_listener(self, pin: str, handler):
        """
        Monitor a button on GPIO `pin` (active-low to GND, internal pull-up) and
        call handler(long_press: bool) on each completed press.

        Long-press threshold is cfg.button_longpress_s (default 1.0s).
        """
        def _loop():
            try:
                from maix import gpio, pinmap
                func = f"GPIO{pin}"
                try:
                    pinmap.set_pin_function(pin, func)
                except Exception:
                    pass
                btn  = gpio.GPIO(func, gpio.Mode.IN, gpio.Pull.PULL_UP)
                last = btn.value()
                press_start = 0.0
                self.logger.info(
                    f"Button listener active on {pin} (active-low)",
                    module="Orchestrator",
                )
                while self._running:
                    v = btn.value()
                    if last == 1 and v == 0:        # falling edge = pressed
                        press_start = time.monotonic()
                    elif last == 0 and v == 1:      # rising edge = released
                        dur = time.monotonic() - press_start
                        long_press = dur >= cfg.get("button_longpress_s", 1.0)
                        handler(long_press)
                        time.sleep(0.05)            # debounce settle
                    last = v
                    time.sleep(0.02)
            except Exception as e:
                self.logger.warn(
                    f"GPIO button unavailable ({pin}): {e}",
                    module="Orchestrator",
                )

        threading.Thread(
            target=_loop, daemon=True, name=f"BtnListener-{pin}"
        ).start()

    # ─── Simulated buttons (web UI) ───────────────────────────────────────────

    def simulate_button(self, which: str, long_press: bool = False) -> bool:
        """
        Inject a MODE/ACTION button press from the web UI. Non-blocking: the
        press is queued and processed on the SimBtn worker thread, so the HTTP
        request returns immediately even if the press triggers a slow NPU model
        reload. Returns False if `which` is invalid or the queue is saturated
        (the press is then dropped rather than allowed to back up → no hang).
        """
        if which not in ("mode", "action"):
            return False
        try:
            self._sim_btn_q.put_nowait((which, bool(long_press)))
            return True
        except queue.Full:
            self.logger.warn(
                "Simulated button dropped — worker busy (queue full)",
                module="Orchestrator",
            )
            return False

    def _sim_button_worker(self):
        """
        Serialize simulated presses onto a single thread, mirroring the physical
        BtnListener exactly. A short get() timeout lets the thread notice
        shutdown (_running=False) promptly so stop() never hangs.
        """
        while self._running:
            try:
                which, long_press = self._sim_btn_q.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                kind = "long" if long_press else "short"
                self.logger.info(
                    f"Simulated {which.upper()} button ({kind} press)",
                    module="Orchestrator",
                )
                if which == "mode":
                    self._on_button(long_press)
                else:
                    self._on_action_button(long_press)
            except Exception as e:
                self.logger.warn(
                    f"Simulated button '{which}' failed: {e}",
                    module="Orchestrator",
                )

    def note_user_interaction(self, window_s: Optional[float] = None):
        """Start/refresh the detection-audio mute window after a user action,
        so the resulting feedback is heard rather than buried under detection
        spam. The press itself barges past the queue separately (user_barge_in)."""
        try:
            w = float(window_s if window_s is not None
                      else cfg.get("detection_mute_after_interaction_s", 6.0))
        except Exception:
            w = 6.0
        self._suppress_det_until = time.monotonic() + w

    def detection_audio_suppressed(self) -> bool:
        """True while detection alerts should stay silent (post-interaction)."""
        return time.monotonic() < self._suppress_det_until

    def _press_cue(self):
        """Acknowledge a button press the instant it lands.

        Barges past any detection spam already queued (flush + instant cue) so
        the press is never stuck waiting in line, and mutes detection audio
        briefly so the action it triggers (mode switch / describe / repeat) is
        actually heard. This is the fix for "device stuck spamming 'orang di
        depan' won't accept button clicks"."""
        if self.audio_manager:
            self.audio_manager.user_barge_in("chime_press.wav")
        self.note_user_interaction()

    def _on_button(self, long_press: bool):
        """Route a completed MODE-button press based on onboarding state."""
        self._press_cue()
        onboarding_active = (
            not cfg.get("setup_completed", False)
            and not cfg.get("url_ack", False)
        )
        if onboarding_active and self.onboarding is not None:
            if long_press:
                self.onboarding.acknowledge()         # "udah paham"
            else:
                self.onboarding.announce(force=True)  # "minta ulang"
            return
        # Normal operation: short press cycles mode; long press re-speaks the
        # web address (the only way a blind user can re-discover the URL later).
        if long_press:
            if self.onboarding is not None:
                self.onboarding.announce(force=True)
        else:
            self.switch_mode(self._MODE_CYCLE[self.mode])

    def _on_action_button(self, long_press: bool):
        """
        ACTION button: on-demand capture (1 press = 1 API call).

          short → describe scene (explorer/context) or scan QRIS (qris mode)
          long  → re-speak the last result the user heard

        Inert during onboarding to avoid confusing first-boot.
        """
        self._press_cue()
        onboarding_active = (
            not cfg.get("setup_completed", False)
            and not cfg.get("url_ack", False)
        )
        if onboarding_active:
            return
        if long_press:
            # Repeat the last thing spoken (description / QRIS result).
            if self.audio_manager:
                last = self.audio_manager.last_caption.get("text", "")
                if last:
                    self.audio_manager.queue_info(last)
            return
        # Short press: trigger the current mode's capture via the same command
        # path the Web UI uses, so it runs on the AI loop thread (not GPIO).
        self.set_pending_command("qris" if self.mode == "qris" else "describe")

    # ─── Thermal throttling callbacks ─────────────────────────────────────────

    def _on_thermal_throttle(self, temp_c: float):
        self.logger.warn(
            f"Thermal throttle engaged at {temp_c:.1f}°C — reducing FPS",
            module="Orchestrator",
        )
        cfg.set("camera_fps", cfg.THERMAL_THROTTLE_FPS)
        if self.audio_manager:
            self.audio_manager.queue_system("suhu_tinggi")

    def _on_thermal_recover(self, temp_c: float):
        self.logger.info(
            f"Thermal recover at {temp_c:.1f}°C — restoring FPS",
            module="Orchestrator",
        )
        cfg.set("camera_fps", cfg.get("camera_fps_normal", 30))

    # ─── Main AI loop ─────────────────────────────────────────────────────────

    # ─── Mode Ambil Data — camera ownership handoff ───────────────────────────
    # Invariant: exactly one of {AIEngine, DataCollector} holds the camera.
    # All three helpers run on the AI-loop thread so open/close never races.

    def _start_aural_engine(self):
        """Construct AIEngine (opens camera + model) and register the watchdog."""
        from core.ai_engine import AIEngine
        self.ai_engine = AIEngine(orchestrator=self, logger=self.logger)
        if self.watchdog:
            self.watchdog.register(
                "ai_engine",
                timeout_s=cfg.WATCHDOG_TIMEOUT_S,
                restart_fn=self.ai_engine.reload,
            )

    def _enter_collection_mode(self, announce: bool = False):
        """Release the aural camera and auto-start dataset capture."""
        # Unregister first so the watchdog can't reload AIEngine (→ reopen camera)
        # while we're in collection mode.
        if self.ai_engine is not None:
            if self.watchdog:
                try:
                    self.watchdog.unregister("ai_engine")
                except Exception:
                    pass
            try:
                self.ai_engine.release()
            except Exception as e:
                self.logger.warn(f"AIEngine release failed: {e}", module="Orchestrator")
            self.ai_engine = None

        self._collection_ready.set()

        # Auto-start: the helper just powers the device on and walks.
        dc = self.data_collector
        if dc is not None and not dc.is_running:
            try:
                dc.start()
            except Exception as e:
                self.logger.warn(f"Auto-start capture failed: {e}", module="Orchestrator")

        if announce and self.audio_manager:
            self.audio_manager.queue(
                "Mode ambil data aktif.", label="datacol_on", cooldown=0,
                wav_name="mode_ambil_data_aktif.wav")
            self.audio_manager.queue(
                "Mengambil data.", label="datacol_capturing", cooldown=0,
                wav_name="mengambil_data.wav")

    def _exit_collection_mode(self):
        """Stop capture, free its camera, and bring the aural engine back."""
        self._collection_ready.clear()
        dc = self.data_collector
        if dc is not None and dc.is_running:
            try:
                dc.stop()                 # joins capture thread, releases camera
            except Exception as e:
                self.logger.warn(f"Stop capture failed: {e}", module="Orchestrator")
        self._start_aural_engine()
        if self.audio_manager:
            self.audio_manager.queue(
                "Mode normal aktif.", label="datacol_off", cooldown=0,
                wav_name="mode_normal_aktif.wav")

    def run_ai_loop(self):
        """Entry point for the AI thread."""
        from core.audio_manager import AudioManager

        # AudioManager is always built — needed for cues/feedback in every mode.
        self.audio_manager = AudioManager(orchestrator=self, logger=self.logger)

        # Mode Ambil Data is sticky across reboots. If the device booted into it,
        # never construct AIEngine (its __init__ would grab the camera the data
        # collector needs); hand the camera straight to capture instead.
        if cfg.get("data_collection_mode", False):
            self.logger.ok(
                "Booting in Mode Ambil Data — aural pipeline skipped",
                module="Orchestrator",
            )
            self._enter_collection_mode(announce=True)
        else:
            self._start_aural_engine()
            self.logger.ok("AI Engine + Audio Manager ready", module="Orchestrator")

        while self._running:
            # Heartbeat from the loop itself: the engine thread is alive even
            # when the camera is down, so the watchdog must NOT reload-hammer.
            # (Repeated camera re-init on a leaked VI channel exhausts buffers
            #  → "No buffer space available" → SIGSEGV. Recovery is handled
            #  gently with backoff inside AIEngine.capture_and_infer instead.)
            if self.watchdog and self.ai_engine is not None:
                self.watchdog.heartbeat("ai_engine")

            # Clear the mode-change event at the top of each cycle
            self._mode_event.clear()

            # Process one pending command from Web UI
            cmd = self.pop_pending_command()
            if cmd:
                self._handle_command(cmd)

            # ── Mode Ambil Data live transitions ──────────────────────────────
            # Both camera open/close happen here on the AI thread so AIEngine and
            # DataCollector never touch the camera concurrently.
            want_collection = cfg.get("data_collection_mode", False)
            if want_collection and self.ai_engine is not None:
                self.logger.info("Switching → Mode Ambil Data", module="Orchestrator")
                self._enter_collection_mode(announce=True)
            elif not want_collection and self.ai_engine is None:
                self.logger.info("Switching → Mode Normal", module="Orchestrator")
                self._exit_collection_mode()

            if want_collection:
                # Camera owned by DataCollector; no inference, no detection audio.
                self._mode_event.wait(timeout=0.2)
                continue

            # Cloud camera-QR pairing: while unpaired, watch frames for a pairing
            # QR shown in the browser and let the device claim itself.
            cloud = getattr(self, "cloud", None)
            if cloud is not None and self.ai_engine is not None and cloud.wants_qr_scan():
                payload = self.ai_engine.scan_pairing_qr()
                if payload:
                    cloud.on_qr_payload(payload)

            # While AI Focus is active, skip inference and wait
            if self.ai_focus:
                self._mode_event.wait(timeout=0.05)
                continue

            mode = self.mode

            if mode == "explorer":
                from modes.explorer_mode import run_explorer_tick
                run_explorer_tick(self)
            elif mode == "context":
                from modes.context_mode import run_context_tick
                run_context_tick(self)
            elif mode == "qris":
                # QRIS only activates on-demand via command; idle here
                self._mode_event.wait(timeout=0.1)
            else:
                self._mode_event.wait(timeout=0.1)

    def _handle_command(self, cmd_obj: dict):
        cmd  = cmd_obj.get("cmd")
        data = cmd_obj.get("data", {})

        # Any web/queued command is a deliberate user action — mute detection
        # spam so its feedback is heard, not buried.
        self.note_user_interaction()

        if cmd == "focus":
            self.activate_ai_focus()

        elif cmd == "set_mode":
            # Flush any detection spam already queued so the confirmation plays
            # immediately (the button path barges in itself; this covers the
            # web /command path where there's no press cue).
            if self.audio_manager:
                self.audio_manager.clear()
            self.switch_mode(data.get("mode", "explorer"))

        elif cmd == "qris":
            if self.ai_engine:
                self.ai_engine.trigger_qris_scan()
            self.note_user_interaction()   # keep the result audible after the scan

        elif cmd == "describe":
            if self.ai_engine:
                self.ai_engine.trigger_scene_description()
            self.note_user_interaction()   # keep the description audible after it returns

        elif cmd == "update_config":
            cfg.update(data)
            self.logger.info(f"Config updated: {list(data.keys())}",
                             module="Orchestrator")

    def stop(self):
        self._running = False
        self._mode_event.set()   # unblock any waiting loop
        if self.audio_manager:
            self.audio_manager.stop()
        # Release the camera explicitly. Without this, a SIGTERM/kill leaves the
        # cvitek VI channel allocated ("No buffer space available"), and the next
        # start SIGSEGVs in the C camera layer before Python can catch it.
        time.sleep(0.2)          # let the AI loop exit its current frame read
        if self.ai_engine:
            try:
                self.ai_engine.release()
            except Exception:
                pass

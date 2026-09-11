"""
Orchestrator — Event-driven state machine & shared state hub.

Mode transitions
────────────────
  switch_mode(new_mode)   Thread-safe; releases resources from the old mode,
                          loads resources for the new one, plays a confirmation
                          audio cue. Can be called from any thread.

Hardware buttons
────────────────
  If cfg.BUTTON_PIN_MODE >= 0, a dedicated thread monitors that GPIO pin and
  cycles through modes on each falling edge (press). Configure the pin number
  in /root/config.json ("button_pin_mode": <N>). A second thread does the same
  for BUTTON_PIN_ACTION (describe / repeat).

  Holding BOTH together opens volume mode — see the volume section below.

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
from utils.power import PowerGovernor, pace_delay

# Contact-bounce settle applied to BOTH button edges (seconds).
_BTN_DEBOUNCE_S = 0.05

# A gap between two GPIO polls larger than this means the listener thread was
# not scheduled — the poll loop paces itself at 20ms, so the only thing that
# produces a gap this size is a C call holding the GIL (camera open, NPU load).
# Press durations measured across such a gap are not real; see the listener.
_BTN_STALL_S = 0.25


class Orchestrator:

    # "idle" is the neutral resting state: camera and NPU released, nothing
    # announced. It is where the device boots and where the mode cycle returns.
    MODES = ("idle", "explorer", "context", "qris")
    # Button press cycles through modes in this order
    _MODE_CYCLE = {"idle": "explorer", "explorer": "context",
                   "context": "qris", "qris": "idle"}

    # Modes that keep YOLO loaded
    _YOLO_MODES = {"explorer"}

    # Neutral mode the device falls back to whenever the configured one is
    # unusable. Never explorer: an unasked-for mode that starts speaking is
    # worse than one that waits for a button press.
    NEUTRAL_MODE = "idle"

    @staticmethod
    def collection_transition(want_collection: bool, in_collection: bool):
        """"enter", "exit", or None — the camera handoff dataset capture needs.

        Takes the ACTUAL capture state, never "is there an AI engine?". That
        proxy held only while collection mode was the single state without an
        engine; idle mode has none either, and inferring from it made every
        tick decide the device had just left capture — re-announcing "Mode
        normal aktif." forever.
        """
        if want_collection and not in_collection:
            return "enter"
        if in_collection and not want_collection:
            return "exit"
        return None

    @staticmethod
    def engine_wanted(mode: str, collecting: bool) -> bool:
        """Whether the AI engine (and with it the camera) should be held.

        Measured on the device: with the camera merely OPEN and never read, the
        app still burned ~25-30% of the single core and the kernel's
        [vi_event_handle] stayed busy — the sensor streams into the VI buffers
        whether or not anyone reads them. So idle really does have to let go of
        the camera, not just stop reading it.

        Dataset capture outranks every mode: exactly one of AIEngine /
        DataCollector may hold the camera at a time.
        """
        if collecting:
            return False
        return mode != "idle"

    @classmethod
    def next_mode(cls, current) -> str:
        """The mode a short MODE-button press moves to.

        An unknown current mode lands on the neutral one: the user's way out of
        any state they did not intend to be in is always one more press.
        """
        return cls._MODE_CYCLE.get(current, cls.NEUTRAL_MODE)

    @classmethod
    def resolve_boot_mode(cls, raw, last_mode=None) -> str:
        """Mode to stand in at power-on, from cfg["boot_mode"].

        Accepts a mode name, or "last" to resume whatever was running before
        the device was switched off. Anything unset or unrecognised resolves to
        the neutral mode rather than guessing.
        """
        value = (raw or "").strip().lower() if isinstance(raw, str) else ""
        if value == "last":
            value = (last_mode or "").strip().lower() if isinstance(last_mode, str) else ""
        if value in cls.MODES:
            return value
        return cls.NEUTRAL_MODE

    def __init__(self, logger):
        self.logger = logger

        # ── Shared state ──────────────────────────────────────────────────────
        self._lock = threading.Lock()

        # Boot mode: neutral by default. A device that wakes up already
        # narrating — in a bag, on a table, mid-handover — is a device nobody
        # asked anything of yet. cfg["boot_mode"] can pin a mode, or "last" to
        # resume the one it was switched off in.
        self._mode      = self.resolve_boot_mode(
            cfg.get("boot_mode"), cfg.get("last_mode")
        )
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

        # ── Adaptive power governor ───────────────────────────────────────────
        # Owns the answer to "how much work is the AI loop allowed to do right
        # now", from temperature and whether anything is actually happening.
        self._power = PowerGovernor(
            full_fps=cfg.get("camera_fps", 30),
            hot_c=cfg.get("thermal_throttle_temp_c", 80.0),
            recover_margin_c=cfg.get("power_recover_margin_c", 5.0),
            idle_after_s=cfg.get("power_idle_after_s", 20.0),
            idle_fps=cfg.get("power_idle_fps", 8.0),
        )
        self._power_plan = self._power.update(now=time.monotonic())

        # Preview bookkeeping: when a client last asked for a frame, and how
        # long after that we keep encoding them. The dashboard polls twice a
        # second, so a few seconds of grace spans normal polling without
        # leaving the encoder running for a closed tab.
        self._last_preview_req = None
        self._preview_grace_s  = cfg.get("preview_grace_s", 5.0)

        # ── Mode-change event (wakes AI loop when mode switches) ──────────────
        self._mode_event = threading.Event()

        # Monotonic timestamp of the last AI-loop iteration, set unconditionally
        # every tick (see run_ai_loop). The hardware watchdog in main.py only
        # pets /dev/watchdog while this is fresh, so a wedged or dead loop lets
        # the SoC reset the board instead of leaving a blind user with a device
        # that loops one phrase forever. Plain float write/read: atomic under
        # the GIL, and a torn value is impossible.
        self._loop_beat = time.monotonic()

        # Set by the Watchdog thread, acted on by the AI loop. See
        # _request_engine_restart for why the watchdog may not do the work
        # itself: it would put a second thread into the cvitek VI path.
        self._engine_restart_requested = False

        # ── Mode Ambil Data: set once the AI loop has released the aural camera
        # and the device is idling in collection mode (camera free for capture).
        self._collection_ready = threading.Event()

        # ── Set by run_ai_loop when its loop exits, so stop() can wait for the
        # AI thread to finish an in-flight frame read before releasing the
        # camera (a blind sleep can race a slow _cam.read() → shutdown segfault).
        self._ai_loop_stopped = threading.Event()

        # ── Hardware buttons (MODE + ACTION) ─────────────────────────────────────
        # Chord state shared by the two listener threads: each one sees only
        # its own pin, so "both held at once" — the gesture that opens volume
        # mode — has to be assembled here rather than inside either loop.
        self._btn_lock     = threading.Lock()
        self._btn_down     = {}       # role -> monotonic ts of its falling edge
        self._btn_consumed = set()    # roles whose release the chord already ate
        self._volume_until = 0.0      # monotonic deadline; 0.0 = mode closed
        self._volume_gen   = 0        # bumped per session; retires stale timers

        mode_pin = self._button_pin()
        if mode_pin:
            self._start_button_listener(mode_pin, "mode", self._on_button)
        action_pin = self._action_pin()
        if action_pin:
            self._start_button_listener(action_pin, "action",
                                        self._on_action_button)

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

        # Camera orientation: the persisted quarter turn plus the frame size it
        # actually produces (utils.orientation is pure, no camera needed).
        try:
            from utils.orientation import normalize_rotation, rotated_dims
            _cam_rot = normalize_rotation(cfg.get("camera_rotation", 0))
            _cam_w, _cam_h = rotated_dims(
                cfg.get("input_width", 320), cfg.get("input_height", 224), _cam_rot
            )
        except Exception:
            _cam_rot = 0
            _cam_w, _cam_h = cfg.get("input_width", 320), cfg.get("input_height", 224)

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
                # Live volume: the device buttons can now change it (volume
                # mode), so a page that only read it once at load would show a
                # stale number for the rest of the session.
                "audio_volume": cfg.AUDIO_VOLUME,
                # Whether the MODE/ACTION buttons are currently bound to volume
                # instead of mode/describe. Nothing used to report this, so a
                # caregiver watching the dashboard saw presses "do nothing" and
                # had no way to know the device was in a modal state — and the
                # web chord is a blind toggle, so their mental model could be
                # exactly inverted from the device's.
                "volume_mode":  self._in_volume_mode(),
                # White-label brand ("auralai" | "isora") — drives the /buttons
                # UI name + which greeting audio set is active. Flipped via the
                # hidden long-press on the logo (POST /brand).
                "brand":        cfg.get("brand", "isora"),
                "scene_verbosity": cfg.get("scene_verbosity", "detail"),
                # Which cloud voice reads descriptions, and (for openai) which
                # one of its voices. "auto" is resolved here rather than in the
                # UI so the page shows what the device will ACTUALLY use.
                "tts_provider":     ("openai" if (
                    str(cfg.get("tts_provider", "gtts")).lower() == "openai"
                    or (str(cfg.get("tts_provider", "gtts")).lower() == "auto"
                        and cfg.OPENAI_API_KEY)) else "gtts"),
                "tts_openai_voice": cfg.get("tts_openai_voice", "alloy"),
                "tts_openai_available": bool(cfg.OPENAI_API_KEY),
                # Per-word audio cache: "caching per-kata" (True) vs "satu blok
                # audio" (False), the inter-word gap (ms; <0 = overlap), the
                # number of warmed words, and recent describe latency.
                "word_cache_enabled": bool(cfg.get("word_cache_enabled", True)),
                "word_cache_gap_ms":  int(cfg.get("word_cache_gap_ms", -10)),
                "word_cache_max_words": int(cfg.get("word_cache_max_words", 12)),
                "cached_words_total": cached_words_total,
                "scene_metrics":      scene_metrics,
                "last_caption": last_caption,
                "battery":      battery,
                "wifi_signal":  wifi["signal"],
                "wifi_ssid":    wifi["ssid"],
                "temperature":  temp_c,
                # What the device decided to do about its own temperature.
                # This is where a hot device reports itself — to the dashboard,
                # where a pendamping can see it, instead of into the ear of the
                # person walking, who can do nothing with the information.
                "power": {
                    "tier":       self._power_plan.tier,
                    "target_fps": self._power_plan.target_fps,
                    "preview":    self._power_plan.preview,
                    "boot_mode":  cfg.get("boot_mode", "idle"),
                },
                "setup_completed": cfg.get("setup_completed", False),
                # Effective (post-rotation) preview size — a quarter turn
                # swaps the axes, so a UI that lays out the preview from these
                # must get the rotated pair, not the raw capture size.
                "cam_w":        _cam_w,
                "cam_h":        _cam_h,
                # Persisted camera orientation (0/90/180/270, clockwise) so the
                # web UI can show which turn is currently active.
                "camera_rotation": _cam_rot,
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

        # NO HARDWARE WORK HERE. switch_mode runs on whichever thread saw the
        # press — either GPIO listener, the SimBtn worker, or an HTTP thread —
        # and it used to load/unload the NPU model inline. That put a C call
        # that holds the GIL on the button thread, racing the AI thread's own
        # camera open/close. Two failures came out of it, both measured:
        #   * the load blocked on the engine lock the AI thread was holding
        #     across a cvitek VI close, and the whole interpreter wedged — no
        #     log, no heartbeat, audio looping one phrase until power was cut;
        #   * when release() won the race, self.ai_engine was already None for
        #     the orchestrator but still bound on the button thread, so the
        #     load allocated an NPU model nobody referenced. 24 loads against
        #     20 releases over 92 switches: four leaks, on a 128MB no-swap board.
        # The model now follows the camera on the AI loop thread (see
        # _sync_engine_to_mode), which is the one thread allowed to touch the
        # sensor at all. Everything left in this method is pure state + audio.
        # No flag is needed: _sync_engine_to_mode is idempotent and runs every
        # tick, and _mode_event below already wakes the loop immediately.

        # Remember it, so a device configured with boot_mode="last" comes back
        # where the user left it. Persisted, not just held in RAM: cfg.set()
        # alone never reaches flash, so boot_mode="last" resumed whatever was
        # in config.json from the previous write rather than the real last mode.
        try:
            cfg.set("last_mode", new_mode)
            cfg.save_async()
        except Exception:
            pass

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

    def _start_button_listener(self, pin: str, role: str, handler):
        """
        Monitor a button on GPIO `pin` (active-low to GND, internal pull-up) and
        call handler(long_press: bool) on each completed press.

        Long-press threshold is cfg.button_longpress_s (default 1.0s).

        `role` ("mode" / "action") is what lets the two independent listener
        threads see each other: every edge is published to the shared chord
        state, and a hold that turns into a chord is swallowed here, so its
        release cannot ALSO fire this button's own action (cycling the mode on
        the way out of volume mode would be its own small disaster).
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
                press_start = None
                self.logger.info(
                    f"Button listener active on {pin} (active-low)",
                    module="Orchestrator",
                )
                last_poll = time.monotonic()
                while self._running:
                    now  = time.monotonic()
                    # Gap since the previous poll. The loop paces itself at
                    # 20ms, so anything far above that means this thread was
                    # not scheduled — almost always because a C call (camera
                    # open, NPU load) was holding the GIL. Press timing taken
                    # across such a gap is fiction, so it is not trusted below.
                    stalled   = (now - last_poll) > _BTN_STALL_S
                    last_poll = now

                    v = btn.value()
                    if last == 1 and v == 0:        # falling edge = pressed
                        press_start = now
                        self._note_button_down(role, press_start)
                        # Debounce the PRESS edge too. Only the release edge
                        # used to settle, so contact bounce on the way down
                        # could register as two presses for one push.
                        time.sleep(_BTN_DEBOUNCE_S)
                        last_poll = time.monotonic()
                    elif last == 0 and v == 1:      # rising edge = released
                        eaten = self._note_button_up(role)
                        # Only fire if we actually observed the press. If the
                        # button was already held when the listener started
                        # (press_start is None), ignore this first release —
                        # otherwise dur is measured from a bogus start and fires
                        # a phantom long-press (e.g. dismissing onboarding).
                        if press_start is not None and not eaten:
                            dur = now - press_start
                            if stalled:
                                # We cannot know when the finger actually left
                                # the pad, only that we were frozen across it.
                                # Resolve to SHORT: a wrong short press cycles
                                # the mode, which one more press undoes, while
                                # a wrong long press re-speaks the URL or
                                # dismisses onboarding — states the user cannot
                                # easily get back out of.
                                long_press = False
                                self.logger.warn(
                                    f"{role} press timing crossed a "
                                    f"{now - press_start:.1f}s stall — treated "
                                    f"as a short press",
                                    module="Orchestrator",
                                )
                            else:
                                long_press = dur >= cfg.get("button_longpress_s", 1.0)
                            # An exception here used to escape the while loop
                            # and kill this listener thread for good: the
                            # physical button went dead until reboot, silently.
                            # The web path always survived the same exception,
                            # which is exactly backwards for the input a blind
                            # user actually has in their hand.
                            try:
                                handler(long_press)
                            except Exception as he:
                                self.logger.error(
                                    f"{role} button handler failed: {he}",
                                    module="Orchestrator",
                                )
                        press_start = None
                        time.sleep(_BTN_DEBOUNCE_S)  # debounce settle
                        last_poll = time.monotonic()
                    elif v == 0 and press_start is not None:
                        # Still held — the other button may be held too.
                        try:
                            self._poll_chord()
                        except Exception as ce:
                            self.logger.warn(f"chord poll failed: {ce}",
                                             module="Orchestrator")
                    last = v
                    time.sleep(0.02)
            except Exception as e:
                # Leaving the loop with this button still marked down would let
                # the OTHER button, held alone, satisfy the chord test forever.
                self._note_button_up(role)
                self.logger.error(
                    f"GPIO button listener for {pin} STOPPED: {e} — "
                    f"this button is dead until restart",
                    module="Orchestrator",
                )

        threading.Thread(
            target=_loop, daemon=True, name=f"BtnListener-{pin}"
        ).start()

    # ─── Volume mode (chord: MODE + ACTION held together) ─────────────────────
    #
    # Why a chord. All four gestures were already spoken for (short/long x
    # MODE/ACTION) and none was free to take: long-press MODE is the only way a
    # blind user rediscovers the web address after setup. A double-tap was the
    # other candidate, but it taxes the gestures that stay — every short press
    # would have to wait out the second-tap window before acting, making every
    # describe and every mode switch slower to pay for a setting people touch
    # once a week. Holding both buttons costs nothing that already works, and is
    # close to impossible to strike by accident.
    #
    # Inside the mode MODE steps down and ACTION steps up, matching the - / +
    # order the same two buttons sit in on the /buttons page. The confirmation
    # chime is played AT the new volume, so the user hears the setting itself
    # rather than a number they would have to turn into loudness in their head.

    @staticmethod
    def step_volume(current, direction, step=10, lo=20, hi=100) -> int:
        """The volume one press moves to. Pure — the whole policy lives here.

        Returning `current` unchanged is the signal for "that press moved
        nothing", which the caller turns into the limit chime.

        Below the floor (reachable only by writing audio_volume from the web UI
        or the cloud push) a DOWN press is a no-op rather than a jump up onto
        the floor: the user asked for quieter, and answering with louder is
        worse than answering with nothing. UP from there lands on the floor, so
        the buttons can always climb back out.
        """
        try:
            cur = int(current)
        except (TypeError, ValueError):
            cur = 80
        try:
            step = max(1, int(step))
        except (TypeError, ValueError):
            step = 10
        try:
            lo, hi = max(0, min(100, int(lo))), max(0, min(100, int(hi)))
        except (TypeError, ValueError):
            lo, hi = 20, 100
        if lo > hi:
            lo, hi = hi, lo
        cur = max(0, min(100, cur))
        if direction > 0:
            return min(hi, max(lo, cur + step))
        if cur <= lo:
            return cur
        return max(lo, min(hi, cur - step))

    def _note_button_down(self, role: str, ts: float):
        with self._btn_lock:
            self._btn_down[role] = ts
            self._btn_consumed.discard(role)

    def _note_button_up(self, role: str) -> bool:
        """Release bookkeeping. True when the chord already ate this hold."""
        with self._btn_lock:
            self._btn_down.pop(role, None)
            eaten = role in self._btn_consumed
            self._btn_consumed.discard(role)
            return eaten

    def _poll_chord(self):
        """Fire the chord once both buttons have been held together long enough.

        Called from both listener threads on every poll while their own button
        is down; the lock plus the consumed set make the two callers converge on
        exactly one fire per hold.
        """
        try:
            hold = float(cfg.get("button_chord_hold_s", 0.6))
        except (TypeError, ValueError):
            hold = 0.6
        now = time.monotonic()
        with self._btn_lock:
            if len(self._btn_down) < 2 or self._btn_consumed:
                return
            # Measured from the LATER press: the gesture is "held together for
            # hold seconds", not "one of them has been down that long" — nobody
            # presses two buttons on the same millisecond.
            if now - max(self._btn_down.values()) < hold:
                return
            self._btn_consumed = set(self._btn_down)
        self._toggle_volume_mode()

    def _in_volume_mode(self) -> bool:
        with self._btn_lock:
            return time.monotonic() < self._volume_until

    def _volume_timeout_s(self) -> float:
        try:
            return max(1.0, float(cfg.get("volume_mode_timeout_s", 5.0)))
        except (TypeError, ValueError):
            return 5.0

    def _toggle_volume_mode(self):
        """The chord opens volume mode; the same chord closes it early."""
        if self._in_volume_mode():
            self._exit_volume_mode()
        else:
            self._enter_volume_mode()

    def _enter_volume_mode(self):
        timeout = self._volume_timeout_s()
        with self._btn_lock:
            self._volume_gen += 1
            gen = self._volume_gen
            self._volume_until = time.monotonic() + timeout
        # Detection alerts would otherwise talk straight over every step chime.
        self.note_user_interaction(timeout + 2.0)
        if self.audio_manager:
            self.audio_manager.user_barge_in("chime_vol_enter.wav")
            # A modal state has to announce that it is modal. Without this a
            # first-time user presses MODE, hears no mode change, and concludes
            # the device is broken rather than that it is listening for volume.
            self.audio_manager.queue_system("atur_volume")
        self.logger.info(
            f"Volume mode ON (chord) — volume {cfg.get('audio_volume')}",
            module="Orchestrator",
        )
        threading.Thread(target=self._volume_mode_timer, args=(gen,),
                         daemon=True, name="VolTimeout").start()

    def _exit_volume_mode(self, gen: Optional[int] = None, quiet: bool = False):
        """Close volume mode and persist the level. Idempotent."""
        with self._btn_lock:
            if self._volume_until <= 0.0:
                return                      # already closed
            if gen is not None and gen != self._volume_gen:
                return                      # a newer session owns the mode
            self._volume_until = 0.0
        # One flash write per session instead of one per tap: cfg.set() already
        # made each step audible (AudioManager re-reads audio_volume on every
        # playback), so this save only has to survive a reboot. SYNCHRONOUS on
        # purpose: closing the mode is the durability point, and stop() relies
        # on it to persist a level the user set moments before shutdown. It runs
        # once per session, not once per tap — the per-tap writes are the ones
        # that go through save_async().
        cfg.save()
        if not quiet and self.audio_manager:
            self.audio_manager.queue_cue("chime_vol_exit.wav")
        self.logger.info(
            f"Volume mode OFF — volume {cfg.get('audio_volume')}",
            module="Orchestrator",
        )

    def _volume_mode_timer(self, gen: int):
        """Close the mode once the user stops adjusting.

        Without a timeout the device would sit in a state the user has to
        remember to leave, and a pocketed device would be one accidental press
        away from silence.
        """
        while self._running:
            with self._btn_lock:
                if gen != self._volume_gen:
                    return                  # superseded by a newer session
                remaining = self._volume_until - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(0.25, remaining))
        self._exit_volume_mode(gen)

    def _volume_step(self, direction: int):
        """One press inside volume mode: step, confirm, hold the mode open.

        The read-modify-write is under _btn_lock. The two GPIO listeners are
        independent threads, so MODE-down and ACTION-up arriving together could
        both read the same starting level and one step was silently lost.
        """
        with self._btn_lock:
            cur = cfg.get("audio_volume", 80)
            new = self.step_volume(
                cur, direction,
                step=cfg.get("volume_step", 10),
                lo=cfg.get("volume_button_min", 20),
                hi=cfg.get("volume_button_max", 100),
            )
            if new != cur:
                cfg.set("audio_volume", new)
        if new != cur:
            # The cfg.set() happened under the lock above so the next playback
            # reads the new level at once. save_async() coalesces the flash
            # write off this thread, so a step that lands in the timer's exit
            # window is still durable — such a step used to change RAM only and
            # was lost on reboot — without ever blocking a button on flash I/O.
            cfg.save_async()
        # Still adjusting — push the idle timeout back, but ONLY for a press
        # that actually moved something. Re-arming on a no-op press meant a
        # user parked at the floor, pressing MODE and hearing nothing change,
        # held the mode open forever with every press — and could never press
        # their way back out to the mode button they were looking for.
        timeout = self._volume_timeout_s()
        if new != cur:
            with self._btn_lock:
                if self._volume_until > 0.0:
                    self._volume_until = time.monotonic() + timeout
            self.note_user_interaction(timeout + 2.0)
        if self.audio_manager:
            if new == cur:
                cue = "chime_vol_limit.wav"
            else:
                cue = "chime_vol_up.wav" if direction > 0 else "chime_vol_down.wav"
            # Barge in so rapid taps each land, cutting the previous tick short.
            self.audio_manager.user_barge_in(cue)
        self.logger.info(f"Volume {cur} -> {new}", module="Orchestrator")

    # ─── Simulated buttons (web UI) ───────────────────────────────────────────

    def simulate_button(self, which: str, long_press: bool = False) -> bool:
        """
        Inject a MODE/ACTION button press from the web UI. Non-blocking: the
        press is queued and processed on the SimBtn worker thread, so the HTTP
        request returns immediately even if the press triggers a slow NPU model
        reload. Returns False if `which` is invalid or the queue is saturated
        (the press is then dropped rather than allowed to back up → no hang).

        "chord" stands in for both buttons held together (volume mode), which a
        web page cannot express as two presses — and which is the only way to
        reach volume mode on a unit whose physical buttons are dead.
        """
        if which not in ("mode", "action", "chord"):
            return False
        try:
            # Capture the modal state AT PRESS TIME. The worker used to test
            # _in_volume_mode() when it finally dequeued, so a press made while
            # volume mode was open — but handled after the 5s timeout closed it
            # — silently changed meaning from "quieter" to "next mode". Under a
            # mash the queue is seconds deep, so this was routine, and from the
            # user's side the device simply did the wrong thing.
            self._sim_btn_q.put_nowait(
                (which, bool(long_press), self._in_volume_mode())
            )
            return True
        except queue.Full:
            self.logger.warn(
                "Simulated button dropped — worker busy (queue full)",
                module="Orchestrator",
            )
            # Tell the USER, not just the log. A dropped press was silent on the
            # device: the only sign was text on a web page, which is exactly the
            # thing the person holding this cannot read. A distinct cue is the
            # difference between "it ignored me" and "it is busy".
            if self.audio_manager:
                try:
                    self.audio_manager.queue_cue("chime_busy.wav")
                except Exception:
                    pass
            return False

    def _sim_button_worker(self):
        """
        Serialize simulated presses onto a single thread, mirroring the physical
        BtnListener exactly. A short get() timeout lets the thread notice
        shutdown (_running=False) promptly so stop() never hangs.
        """
        while self._running:
            try:
                which, long_press, was_volume = self._sim_btn_q.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                kind = "long" if long_press else "short"
                self.logger.info(
                    f"Simulated {which.upper()} button ({kind} press)",
                    module="Orchestrator",
                )
                if which == "chord":
                    self._toggle_volume_mode()
                elif which == "mode":
                    self._on_button(long_press, in_volume=was_volume)
                else:
                    self._on_action_button(long_press, in_volume=was_volume)
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

    def loop_healthy(self, stale_after_s: float = 45.0) -> bool:
        """Whether the AI loop has ticked recently enough to count as alive.

        This is the liveness signal the hardware watchdog pets from. It is
        deliberately about the LOOP, not about the engine: idle mode has no
        engine at all, and a loop that dies in idle used to look identical to
        a healthy one.
        """
        try:
            return (time.monotonic() - self._loop_beat) < float(stale_after_s)
        except Exception:
            return True

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

    def _on_button(self, long_press: bool, in_volume: Optional[bool] = None):
        """Route a completed MODE-button press based on onboarding state.

        `in_volume` is the modal state as it was WHEN THE PRESS HAPPENED. The
        GPIO listeners call the handler immediately and pass None, so the live
        check below applies; the queued web path passes what it captured at
        enqueue time, because a press can sit in the queue long enough for the
        volume-mode timeout to change its meaning underneath it.
        """
        # Volume mode owns both buttons while it is open, and answers with its
        # own cue — so this returns before the generic press chime, which would
        # otherwise play at the OLD volume and muddle the level being judged.
        if self._in_volume_mode() if in_volume is None else in_volume:
            self._volume_step(-1)                     # MODE = quieter
            return
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
            self.switch_mode(self.next_mode(self.mode))

    def _on_action_button(self, long_press: bool,
                          in_volume: Optional[bool] = None):
        """
        ACTION button: on-demand capture (1 press = 1 API call).

          short → describe scene (explorer/context) or scan QRIS (qris mode)
          long  → re-speak the last result the user heard

        Inert during onboarding to avoid confusing first-boot; steps the volume
        up instead while volume mode is open.

        `in_volume` — see _on_button: the modal state as it was when the press
        happened, so a queued press cannot be re-read against a mode that has
        since timed out.
        """
        if self._in_volume_mode() if in_volume is None else in_volume:
            self._volume_step(+1)                     # ACTION = louder
            return
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

    # ─── Adaptive power management ────────────────────────────────────────────

    def on_health_sample(self, snapshot: dict):
        """Fold one HealthMonitor sample into the current power plan.

        Called ~every poll from the monitor thread. Deliberately silent: the
        device answers heat by doing less, never by asking the person wearing
        it to intervene. The only outward sign is a log line on a tier change
        and the tier shown on the dashboard.
        """
        temp_c = snapshot.get("cpu_temp_c") if isinstance(snapshot, dict) else None
        before = self._power_plan.tier
        plan   = self._power.update(
            temp_c=temp_c,
            now=time.monotonic(),
            busy=self._recently_busy(),
        )
        with self._lock:
            self._power_plan = plan
        if plan.tier != before:
            shown = f"{temp_c:.1f}°C" if isinstance(temp_c, (int, float)) else "?"
            self.logger.info(
                f"Power tier {before} → {plan.tier} at {shown} "
                f"(fps {plan.target_fps:g}, "
                f"preview {'on' if plan.preview else 'off'})",
                module="Orchestrator",
            )

    def _recently_busy(self) -> bool:
        """True while something is happening that justifies the full rate.

        A scene with nothing in it, and no user asking for anything, is the
        cheapest thing the device will ever look at — there is no reason to
        look at it thirty times a second.
        """
        with self._lock:
            if self._detections:
                return True
        return (
            self.ai_focus
            or self._pending_command is not None
            or self.detection_audio_suppressed()   # a user just interacted
        )

    @property
    def power_plan(self):
        """Current work budget (see utils.power.PowerPlan)."""
        with self._lock:
            return self._power_plan

    def note_preview_request(self, now: float = None):
        """Record that a client just fetched /snapshot (or the MJPEG stream)."""
        with self._lock:
            self._last_preview_req = time.monotonic() if now is None else now

    def wants_preview(self, now: float = None) -> bool:
        """True when it is worth spending a tick encoding the dashboard JPEG.

        Two independent vetoes. Nobody watching: the encode is ~17 ms of an
        ~18 ms tick on this SoC, and the device used to pay it all day for a
        page no one had open. Too hot: heat outranks a watcher — the preview is
        the first work shed, because it is the only work that is not navigation.
        """
        if not self.power_plan.preview:
            return False
        now = time.monotonic() if now is None else now
        with self._lock:
            last = self._last_preview_req
        return last is not None and (now - last) <= self._preview_grace_s

    def tick_delay(self, elapsed_s: float) -> float:
        """Seconds the AI loop must rest after a tick that took `elapsed_s`.

        Pacing is where a plan turns into heat that is never generated. The
        loop waits on the mode event rather than sleeping, so a button press
        still lands instantly even when the budget is two frames a second.
        """
        return pace_delay(self.power_plan, elapsed_s)

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
                # NOT ai_engine.reload. That runs on the Watchdog thread and
                # begins with release() -> _cam.close(), putting a SECOND
                # thread into the cvitek VI open/close path — which the AI loop
                # may be inside at that very moment. Observed on hardware: a
                # mode mash stopped the heartbeat during a teardown, the
                # watchdog fired reload, and the board reset. The watchdog may
                # only ASK; the AI thread does the work.
                restart_fn=self._request_engine_restart,
            )

    def _request_engine_restart(self):
        """Watchdog callback. Sets a flag; touches NO hardware.

        Runs on the Watchdog thread, which must never enter the camera path —
        exactly one thread (the AI loop) is allowed there. If the AI loop is
        wedged inside a C call this request simply never gets picked up, which
        is the honest outcome: no Python code can recover that, and the SoC
        hardware watchdog is the only thing that can.
        """
        self._engine_restart_requested = True
        self.logger.warn(
            "AI engine heartbeat missed — restart requested (will run on the "
            "AI loop thread)",
            module="Orchestrator",
        )

    def _service_engine_restart_request(self):
        """Honour a watchdog restart request. AI-LOOP THREAD ONLY."""
        if not self._engine_restart_requested:
            return
        self._engine_restart_requested = False
        if self.ai_engine is None:
            return
        self.logger.warn("Restarting AI engine on the AI loop thread",
                         module="Orchestrator")
        self._release_aural_engine()
        self._start_aural_engine()

    def _sync_engine_to_mode(self, mode: str):
        """Make the NPU model match the mode. AI-LOOP THREAD ONLY.

        Coalescing lives here, and it is the whole point: the loop asks "should
        the model be loaded for the mode I am in NOW?", so ten mode presses
        during one camera open collapse into at most one load and one release
        instead of ten open/close cycles queued behind each other. Only a mode
        that actually changed the answer costs anything.
        """
        engine = self.ai_engine
        if engine is None:
            return
        want = mode in self._YOLO_MODES
        try:
            if want:
                engine.reload_model()
            else:
                engine.release_model()
        except Exception as e:
            self.logger.warn(f"Model sync failed for mode {mode}: {e}",
                             module="Orchestrator")

    def _release_aural_engine(self):
        """Let go of the camera + NPU. AI-LOOP THREAD ONLY.

        Same invariant as the collection-mode handoff: every camera open/close
        happens on this one thread.

        The watchdog entry is now dropped AFTER release() returns, not before.
        Unregistering first left the single most dangerous call in the program —
        the cvitek VI close, which is where the device was observed to wedge —
        as the one window with no supervision at all: that unregister plus the
        `ai_engine is not None` gate on the loop's own heartbeat meant nothing
        was being watched while the camera closed. Note this only makes the
        hang VISIBLE; it cannot recover it, because the blocked close holds the
        GIL and no Python thread runs. Actual recovery is the SoC hardware
        watchdog armed in main.py.
        """
        if self.ai_engine is None:
            return
        engine = self.ai_engine
        try:
            engine.release()
        except Exception as e:
            self.logger.warn(f"AIEngine release failed: {e}", module="Orchestrator")
        finally:
            if self.watchdog:
                try:
                    self.watchdog.unregister("ai_engine")
                except Exception:
                    pass
        self.ai_engine = None
        self.detections = []

    def _enter_collection_mode(self, announce: bool = False):
        """Release the aural camera and auto-start dataset capture."""
        self._release_aural_engine()
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
        # Only reopen the camera if the mode we are returning to wants it —
        # leaving collection while parked in idle should stay camera-free.
        if self.engine_wanted(self.mode, collecting=False):
            self._start_aural_engine()
        if self.audio_manager:
            self.audio_manager.queue(
                "Mode normal aktif.", label="datacol_off", cooldown=0,
                wav_name="mode_normal_aktif.wav")

    def run_ai_loop(self):
        """Entry point for the AI thread.

        _ai_loop_stopped is stop()'s handshake — it has to be set on EVERY exit
        path, not just a clean `while` exit. If anything escapes the body (a
        MemoryError on this no-swap board, an NPU error out of the pairing-QR
        scan, a failure constructing AudioManager), stop() would otherwise block
        its full 2.0s and then release() the camera with no idea whether this
        thread was still mid-read.
        """
        try:
            self._run_ai_loop_body()
        except Exception as e:
            self.logger.error(f"AI loop died: {e}", module="Orchestrator")
        finally:
            self._ai_loop_stopped.set()

    def _run_ai_loop_body(self):
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
        elif not self.engine_wanted(self.mode, collecting=False):
            # Booted into the neutral mode: never open the camera in the first
            # place. Opening it just to close it on the first tick would cost a
            # sensor init (and the VI channel churn that goes with it) for
            # nothing.
            self.logger.ok(
                f"Booting in mode '{self.mode}' — camera stays closed",
                module="Orchestrator",
            )
        else:
            self._start_aural_engine()
            self.logger.ok("AI Engine + Audio Manager ready", module="Orchestrator")

        while self._running:
            # A tick must NEVER kill the AI thread, so the ENTIRE body is guarded
            # — not just the inference dispatch. The collection-mode transitions
            # and the pairing-QR scan open and close the camera, and
            # _handle_command runs arbitrary web-queued work; all of them can
            # raise types the engine's own handler doesn't catch (NPU errors
            # under memory pressure, MemoryError on this no-swap board). If one
            # escaped, heartbeats would stop and the watchdog would reload-hammer
            # the camera (→ VI buffer exhaustion → SIGSEGV), leaving a blind user
            # with a silent, then crashing, device. Log it, pause briefly to
            # avoid a tight error-spin, and keep looping.
            try:
                # Heartbeat from the loop itself: the engine thread is alive even
                # when the camera is down, so the watchdog must NOT reload-hammer.
                # (Repeated camera re-init on a leaked VI channel exhausts buffers
                #  → "No buffer space available" → SIGSEGV. Recovery is handled
                #  gently with backoff inside AIEngine.capture_and_infer instead.)
                if self.watchdog and self.ai_engine is not None:
                    self.watchdog.heartbeat("ai_engine")

                # Liveness of the LOOP, independent of whether an engine exists.
                # The heartbeat above is gated on ai_engine, which is None for
                # the whole of idle — the default boot mode — so a loop that
                # died or wedged in idle was indistinguishable from a healthy
                # one. This timestamp is what the hardware watchdog pets from,
                # so idle is now supervised like every other mode.
                self._loop_beat = time.monotonic()

                # Clear the mode-change event at the top of each cycle
                self._mode_event.clear()

                # Process one pending command from Web UI
                cmd = self.pop_pending_command()
                if cmd:
                    self._handle_command(cmd)

                # ── Mode Ambil Data live transitions ──────────────────────────
                # Both camera open/close happen here on the AI thread so AIEngine
                # and DataCollector never touch the camera concurrently.
                want_collection = cfg.get("data_collection_mode", False)
                move = self.collection_transition(
                    want_collection, self._collection_ready.is_set()
                )
                if move == "enter":
                    self.logger.info("Switching → Mode Ambil Data", module="Orchestrator")
                    self._enter_collection_mode(announce=True)
                elif move == "exit":
                    self.logger.info("Switching → Mode Normal", module="Orchestrator")
                    self._exit_collection_mode()

                if want_collection:
                    # Camera owned by DataCollector; no inference, no detection audio.
                    self._mode_event.wait(timeout=0.2)
                    continue

                # Cloud camera-QR pairing: while unpaired, watch frames for a
                # pairing QR shown in the browser and let the device claim itself.
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

                # ── Camera ownership follows the mode ─────────────────────────
                # Done HERE, on the AI thread, for the same reason the
                # collection-mode handoff is: the cvitek VI open/close path
                # admits exactly one thread, and a switch_mode() call arrives
                # on the button/web thread.
                if self.engine_wanted(mode, collecting=False):
                    if self.ai_engine is None:
                        self.logger.info(f"Mode {mode} needs the camera — starting engine",
                                         module="Orchestrator")
                        self._start_aural_engine()
                elif self.ai_engine is not None:
                    self.logger.info("Idle — releasing camera and NPU",
                                     module="Orchestrator")
                    self._release_aural_engine()

                # A watchdog restart request is honoured HERE, on the one thread
                # allowed to open or close the camera.
                self._service_engine_restart_request()

                # The NPU model follows the camera, on this same thread. Moved
                # here out of switch_mode: see the comment there for the freeze
                # and the leak this ordering fixes.
                self._sync_engine_to_mode(mode)

                started = time.monotonic()
                if mode == "explorer":
                    from modes.explorer_mode import run_explorer_tick
                    run_explorer_tick(self)
                elif mode == "context":
                    from modes.context_mode import run_context_tick
                    run_context_tick(self)
                elif mode == "idle":
                    from modes.idle_mode import run_idle_tick
                    run_idle_tick(self)
                    continue                      # parks itself; nothing to pace
                elif mode == "qris":
                    # QRIS only activates on-demand via command; idle here
                    self._mode_event.wait(timeout=0.1)
                    continue
                else:
                    self._mode_event.wait(timeout=0.1)
                    continue

                # ── Pace the tick to the power plan ───────────────────────────
                # Without this the loop runs flat out and the "throttle" was
                # pure theatre: it wrote camera_fps to an already-open camera
                # and bought no idle time at all. Waiting on the mode event
                # rather than sleeping keeps a button press instant even when
                # the budget is two frames a second.
                rest = self.tick_delay(time.monotonic() - started)
                if rest > 0:
                    self._mode_event.wait(timeout=rest)
            except Exception as e:
                self.logger.warn(f"AI tick error ({self.mode}): {e}",
                                 module="Orchestrator")
                self._mode_event.wait(timeout=0.5)

    def _say_no_camera(self):
        """Answer a capture request made in a mode that has no camera.

        idle is the DEFAULT boot mode and holds no engine, so pressing ACTION
        on a freshly powered device did nothing at all: no sound, no log line
        the user could hear, nothing. For someone who cannot see a screen that
        is indistinguishable from a dead device, and the natural response is to
        press harder and more often — which is how the mash that wedged the
        unit started. Say what is actually true instead.
        """
        if not self.audio_manager:
            return
        try:
            self.audio_manager.queue_system("kamera_belum_aktif_tekan_mode_dulu")
        except Exception:
            pass

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
            else:
                self._say_no_camera()
            self.note_user_interaction()   # keep the result audible after the scan

        elif cmd == "describe":
            if self.ai_engine:
                self.ai_engine.trigger_scene_description()
            else:
                self._say_no_camera()
            self.note_user_interaction()   # keep the description audible after it returns

        elif cmd == "update_config":
            cfg.update(data)
            self.logger.info(f"Config updated: {list(data.keys())}",
                             module="Orchestrator")

    def stop(self):
        self._running = False
        self._mode_event.set()   # unblock any waiting loop
        # Persist a volume the user was mid-way through setting: the steps live
        # in memory until the mode closes, and a shutdown here would otherwise
        # throw them away. quiet=True — nobody needs an exit chime on the way
        # down, and the audio manager is about to stop anyway.
        self._exit_volume_mode(quiet=True)
        if self.audio_manager:
            self.audio_manager.stop()
        # Wait for the AI loop to leave its body BEFORE touching anything that
        # opens or closes the camera. The AI thread is the only thread allowed in
        # the cvitek VI open/close path (see _run_ai_loop_body) and it may be
        # inside _enter_collection_mode() -> dc.start() or _exit_collection_mode()
        # -> dc.stop() at this very moment. A second thread entering that path
        # leaks the VI channel ("No buffer space available" → SIGSEGV on the next
        # start), and a blind sleep races a slow _cam.read() the same way.
        # Long enough to actually cover the slowest legitimate tick. At 2.0s
        # this "wait" expired during any cloud describe and the shutdown walked
        # straight into the camera teardown below WHILE the AI thread was still
        # reading frames — the exact two-threads-in-the-VI-path bug the comment
        # above exists to prevent.
        handshake_ok = self._ai_loop_stopped.wait(timeout=20.0)
        if not handshake_ok:
            self.logger.warn(
                "AI loop did not stop in 20s — leaving the camera to the "
                "process exit rather than closing it under a live read",
                module="Orchestrator",
            )
        # Stop dataset capture if we're in Mode Ambil Data — otherwise its camera
        # (VI channel) and CSV file leak on shutdown and the next start SIGSEGVs
        # in the C camera layer. stop() is a no-op if capture isn't running.
        if self.data_collector is not None:
            try:
                self.data_collector.stop()
            except Exception:
                pass
        # Release the camera explicitly. Without this, a SIGTERM/kill leaves the
        # cvitek VI channel allocated ("No buffer space available"), and the next
        # start SIGSEGVs in the C camera layer before Python can catch it.
        if self.ai_engine and handshake_ok:
            try:
                self.ai_engine.release()
            except Exception:
                pass

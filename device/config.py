"""
AuralAI SDK — Dynamic configuration
Loaded from /root/config.json at startup; updatable at runtime via companion API.
"""

import os
import json
import threading
from pathlib import Path

_CONFIG_PATH = Path("/root/config.json")

_DEFAULTS: dict = {
    "model_path":               "/root/models/yolo11n.mud",
    # Min YOLO confidence. Raised from 0.5 → 0.6: yolo11n at 320×224 emits
    # stable mid-confidence "person" boxes on cluttered/blurred non-person
    # scenes; 0.6 trims those while keeping real (closer) people that score
    # higher. Pair with the detection de-flicker below. Tune per-device.
    "conf_threshold":           0.6,
    "iou_threshold":            0.45,
    "input_width":              320,
    "input_height":             224,
    "camera_fps":               30,
    "snapshot_interval_ms":     500,
    "web_host":                 "0.0.0.0",
    "web_port":                 8080,
    "ai_focus_duration_s":      5,
    "audio_dir":                "/root/audio",
    "audio_cooldown_s":         2.0,
    "danger_area_threshold":    0.15,
    # ── Detection de-flicker (anti false-positive) ────────────────────────────
    # A detected label must persist in roughly the same spot for this many
    # consecutive frames before it's emitted/announced. Filters YOLO phantom
    # boxes that flicker/teleport on a covered or blurred lens. Set to 1 to
    # disable. detection_max_center_move is the max normalized (0..1) per-frame
    # box-center jump still treated as the "same" object.
    "detection_min_streak":      3,
    "detection_max_center_move": 0.25,
    # ── AI provider ───────────────────────────────────────────────────────────
    # active provider: "openai" | "gemini" | "claude"
    "ai_provider":              "openai",
    "ai_timeout_s":             15,
    # OpenAI
    "openai_api_key":           "",
    "openai_model":             "gpt-4o-mini",
    "openai_timeout_s":         10,   # kept for backward-compat; ai_timeout_s is used
    # Gemini
    "gemini_api_key":           "",
    "gemini_model":             "gemini-1.5-flash",
    # Claude (Anthropic)
    "claude_api_key":           "",
    "claude_model":             "claude-haiku-4-5-20251001",
    # Prompts (runtime-editable)
    "prompt_scene": (
        "Deskripsikan scene ini secara singkat dalam Bahasa Indonesia, "
        "fokus pada objek yang relevan untuk pengguna tunanetra. "
        "Maksimal 2 kalimat."
    ),
    "prompt_qris": (
        "Baca kode QRIS ini. Sebutkan: nama merchant dan nominal jika ada. "
        "Format: MERCHANT: [nama], NOMINAL: [angka]. "
        "Jika bukan QRIS, jawab: BUKAN QRIS."
    ),
    "log_path":                 "/root/logs",
    "log_max_lines":            500,
    "thermal_throttle_temp_c":  80.0,
    "thermal_throttle_fps":     10,
    "watchdog_timeout_s":       5.0,
    # ── Hardware buttons (active-low to GND; internal pull-up, no resistor) ───
    # The GPIO listener enables PULL_UP, so any free standard GPIO works — wire
    # each button: leg1 → pad, leg2 → GND. DO NOT use A26: it is WiFi EN on the
    # WiFi board variant and a button there can toggle WiFi by accident.
    # MODE button pad ("A14" recommended; "" or -1 = disabled). Short press
    # cycles mode / repeats URL during onboarding; long press = web address / ack.
    "button_pin_mode":          "A14",
    # ACTION button pad ("A15" recommended; "" or -1 = disabled). Short press
    # captures on demand (describe / QRIS scan); long press repeats last result.
    # Safe alternates if A15 is taken: A22–A25 (only when SPI4 is unused).
    "button_pin_action":        "A15",
    # Speaker volume (0-100); read by AudioManager on every play
    "audio_volume":             80,
    # Auth: device token (auto-generated on first boot if empty)
    "device_token":             "",
    # CORS: list of allowed origins for dashboard. Empty list = same-origin only.
    # Use ["*"] for wide-open (NOT recommended for pilot).
    "cors_allowed_origins":     ["*"],
    # Auth: require token on POST mutate endpoints (False = legacy/dev-only)
    "auth_required":            True,
    # Settings autosave (UI hint; backend always persists immediately)
    "autosave_enabled":         True,
    # QRIS verification mode: "online" | "offline" | "hybrid"
    "qris_mode":                "hybrid",
    # Maximum acceptable QRIS nominal in IDR before requiring extra confirm
    "qris_nominal_warn_cap":    1_000_000,
    # API key encryption lock — when True, web UI cannot overwrite
    # encrypted keys. Unlock procedure: tools/unlock_keys.py on device.
    "api_keys_locked":          False,
    # TTS hybrid: synthesize dynamic text via gTTS and cache on device
    "tts_enabled":              True,
    "tts_cache_dir":            "/root/audio/tts_cache",
    # I2C battery HAT: enabled only after manual probe via /i2c-probe endpoint
    "i2c_battery_enabled":      False,
    # Companion redesign (handoff §4.3) — audio playback preference
    # "chime"  → only pre-recorded chimes, skip TTS
    # "speech" → only TTS, skip chimes
    # "both"   → chime then TTS (legacy behavior)
    "audio_mode":               "both",
    # Companion redesign (handoff §1) — admin role token. If empty, every
    # holder of device_token can reach /admin. If set, only admin_role_token
    # holders can. Companion (`/`) always works with device_token.
    "admin_role_token":         "",
    # Companion redesign (handoff §6.2) — first-time setup gate. When False,
    # `/` redirects to `/setup` wizard. Set to True at the end of the wizard
    # or manually after provisioning.
    "setup_completed":          False,
    # Asset directory for `/assets/*` static serving + manifest.json.
    # Photos that override the SVG mockups in /guide land here.
    "assets_dir":               "/root/assets",
    # ── Mode Ambil Data (data-collection mode) ────────────────────────────────
    # When True, the device skips the entire aural pipeline (setup nag, object
    # detection, audio alerts) and dedicates the camera to dataset capture.
    # Persistent — survives reboot (stored here in /root/config.json), so the
    # device comes back up in this mode after a power cycle. Toggled live from
    # the /collect page (POST /collect/mode). Lets a non-technical sighted helper
    # carry the device around just to collect photos.
    "data_collection_mode":     False,
    # ── Device identity & spoken-URL onboarding (multi-device) ────────────────
    # Friendly device name; "" → auto "aural-<mac-suffix>" (see utils/identity).
    # Becomes the mDNS `.local` label, so it must stay DNS-safe (UI sanitizes it).
    "device_name":              "",
    # Publish <device_name>.local via mDNS so the dashboard URL survives DHCP.
    "mdns_enabled":             True,
    # Speak the dashboard URL over the speaker during first-time setup.
    "url_announce_enabled":     True,
    # Set True (button long-press) once the helper has heard/understood the URL.
    "url_ack":                  False,
    # Hardware button long-press threshold (s) — long = acknowledge / reserved.
    "button_longpress_s":       1.0,
    # ── Cloud pairing (auralai web hub) ───────────────────────────────────────
    # When True, once online the device registers with the cloud relay, speaks a
    # short pairing code, and pulls config pushed from the web. Offline-safe:
    # if the cloud is unreachable it falls back to the local spoken-URL setup.
    "cloud_enabled":            True,
    # Base URL of the deployed web hub (Vercel). Override for local testing, e.g.
    # "http://<your-pc-ip>:3000". Production: your auralai.app / *.vercel.app URL.
    "cloud_base_url":           "https://aural-ai-six.vercel.app",
    # Identity on the cloud relay — generated once on first online boot.
    "cloud_device_id":          "",
    "cloud_device_secret":      "",
    # E2E keypair for receiving encrypted API keys (see utils/crypto_box).
    "device_pubkey":            "",
    "device_privkey_enc":       "",
    # Set True once the device has been claimed by a user account via a code.
    "paired":                   False,
    # Long-poll timeout (s) the device waits per /api/poll request.
    "cloud_poll_timeout_s":     35,
}


class Config:
    """
    Thread-safe configuration backed by /root/config.json.
    Call cfg.update(dict) to change values at runtime — persisted to disk.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._data: dict = dict(_DEFAULTS)
        self._load()

    # ─── Persistence ──────────────────────────────────────────────────────────

    def _load(self):
        try:
            with open(_CONFIG_PATH) as f:
                loaded = json.load(f)
            with self._lock:
                self._data.update(loaded)
        except FileNotFoundError:
            self._write_defaults()
        except Exception:
            pass

    def _write_defaults(self):
        try:
            _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(_CONFIG_PATH, "w") as f:
                json.dump(_DEFAULTS, f, indent=2)
        except Exception:
            pass

    def save(self):
        """Persist current config to disk."""
        with self._lock:
            data = dict(self._data)
        try:
            with open(_CONFIG_PATH, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    # ─── Read / Write ─────────────────────────────────────────────────────────

    def get(self, key: str, default=None):
        with self._lock:
            return self._data.get(key, default)

    def set(self, key: str, value):
        with self._lock:
            self._data[key] = value

    def update(self, mapping: dict):
        """Merge mapping into config and save to disk."""
        with self._lock:
            self._data.update(mapping)
        self.save()

    def as_dict(self) -> dict:
        with self._lock:
            return dict(self._data)

    # ─── Typed properties ─────────────────────────────────────────────────────

    @property
    def MODEL_PATH(self) -> str:
        return self.get("model_path")

    @property
    def CONF_THRESHOLD(self) -> float:
        return self.get("conf_threshold")

    @property
    def IOU_THRESHOLD(self) -> float:
        return self.get("iou_threshold")

    @property
    def INPUT_WIDTH(self) -> int:
        return self.get("input_width")

    @property
    def INPUT_HEIGHT(self) -> int:
        return self.get("input_height")

    @property
    def CAMERA_FPS(self) -> int:
        return self.get("camera_fps")

    @property
    def SNAPSHOT_INTERVAL_MS(self) -> int:
        return self.get("snapshot_interval_ms")

    @property
    def WEB_HOST(self) -> str:
        return self.get("web_host")

    @property
    def WEB_PORT(self) -> int:
        return self.get("web_port")

    @property
    def AI_FOCUS_DURATION_S(self) -> int:
        return self.get("ai_focus_duration_s")

    @property
    def AUDIO_DIR(self) -> str:
        return self.get("audio_dir")

    @property
    def AUDIO_COOLDOWN_S(self) -> float:
        return self.get("audio_cooldown_s")

    @property
    def DANGER_AREA_THRESHOLD(self) -> float:
        return self.get("danger_area_threshold")

    @property
    def AI_PROVIDER(self) -> str:
        return self.get("ai_provider", "openai")

    @property
    def AI_TIMEOUT_S(self) -> int:
        return self.get("ai_timeout_s", 15)

    @property
    def OPENAI_API_KEY(self) -> str:
        try:
            from utils.secure_keys import read_secret
            v = read_secret(self, "openai_api_key", "OPENAI_API_KEY")
            if v:
                return v
        except Exception:
            pass
        return os.environ.get("OPENAI_API_KEY") or self.get("openai_api_key", "")

    @property
    def OPENAI_MODEL(self) -> str:
        return self.get("openai_model")

    @property
    def OPENAI_TIMEOUT_S(self) -> int:
        return self.get("openai_timeout_s")

    @property
    def GEMINI_API_KEY(self) -> str:
        try:
            from utils.secure_keys import read_secret
            v = read_secret(self, "gemini_api_key", "GEMINI_API_KEY")
            if v:
                return v
        except Exception:
            pass
        return os.environ.get("GEMINI_API_KEY") or self.get("gemini_api_key", "")

    @property
    def GEMINI_MODEL(self) -> str:
        return self.get("gemini_model", "gemini-1.5-flash")

    @property
    def CLAUDE_API_KEY(self) -> str:
        try:
            from utils.secure_keys import read_secret
            v = read_secret(self, "claude_api_key", "ANTHROPIC_API_KEY")
            if v:
                return v
        except Exception:
            pass
        return os.environ.get("ANTHROPIC_API_KEY") or self.get("claude_api_key", "")

    @property
    def CLAUDE_MODEL(self) -> str:
        return self.get("claude_model", "claude-haiku-4-5-20251001")

    @property
    def LOG_PATH(self) -> str:
        return self.get("log_path")

    @property
    def LOG_MAX_LINES(self) -> int:
        return self.get("log_max_lines")

    @property
    def THERMAL_THROTTLE_TEMP_C(self) -> float:
        return self.get("thermal_throttle_temp_c")

    @property
    def THERMAL_THROTTLE_FPS(self) -> int:
        return self.get("thermal_throttle_fps")

    @property
    def WATCHDOG_TIMEOUT_S(self) -> float:
        return self.get("watchdog_timeout_s")

    @property
    def BUTTON_PIN_MODE(self) -> int:
        return self.get("button_pin_mode")

    @property
    def BUTTON_PIN_ACTION(self) -> int:
        return self.get("button_pin_action")

    @property
    def AUDIO_VOLUME(self) -> int:
        return int(self.get("audio_volume", 80))

    @property
    def PROMPT_SCENE(self) -> str:
        return self.get("prompt_scene", _DEFAULTS["prompt_scene"])

    @property
    def PROMPT_QRIS(self) -> str:
        return self.get("prompt_qris", _DEFAULTS["prompt_qris"])

    @property
    def AUTH_REQUIRED(self) -> bool:
        return bool(self.get("auth_required", True))

    @property
    def CORS_ALLOWED_ORIGINS(self) -> list:
        v = self.get("cors_allowed_origins", ["*"])
        return v if isinstance(v, list) else [str(v)]

    @property
    def AUTOSAVE_ENABLED(self) -> bool:
        return bool(self.get("autosave_enabled", True))

    @property
    def QRIS_MODE(self) -> str:
        m = self.get("qris_mode", "hybrid")
        return m if m in ("online", "offline", "hybrid") else "hybrid"

    @property
    def QRIS_NOMINAL_WARN_CAP(self) -> int:
        return int(self.get("qris_nominal_warn_cap", 1_000_000))

    @property
    def API_KEYS_LOCKED(self) -> bool:
        return bool(self.get("api_keys_locked", False))

    @property
    def TTS_ENABLED(self) -> bool:
        return bool(self.get("tts_enabled", True))

    @property
    def TTS_CACHE_DIR(self) -> str:
        return self.get("tts_cache_dir", "/root/audio/tts_cache")

    @property
    def I2C_BATTERY_ENABLED(self) -> bool:
        return bool(self.get("i2c_battery_enabled", False))

    @property
    def AUDIO_MODE(self) -> str:
        """Audio playback preference: "chime" | "speech" | "both". Defaults to "both"."""
        m = self.get("audio_mode", "both")
        return m if m in ("chime", "speech", "both") else "both"

    @property
    def ADMIN_ROLE_TOKEN(self) -> str:
        return self.get("admin_role_token", "") or ""

    @property
    def SETUP_COMPLETED(self) -> bool:
        return bool(self.get("setup_completed", False))

    @property
    def ASSETS_DIR(self) -> str:
        return self.get("assets_dir", "/root/assets")

    @property
    def DEVICE_NAME(self) -> str:
        return self.get("device_name", "") or ""

    @property
    def MDNS_ENABLED(self) -> bool:
        return bool(self.get("mdns_enabled", True))

    @property
    def URL_ANNOUNCE_ENABLED(self) -> bool:
        return bool(self.get("url_announce_enabled", True))

    @property
    def URL_ACK(self) -> bool:
        return bool(self.get("url_ack", False))

    @property
    def BUTTON_LONGPRESS_S(self) -> float:
        return float(self.get("button_longpress_s", 1.0))

    @property
    def CLOUD_ENABLED(self) -> bool:
        return bool(self.get("cloud_enabled", True))

    @property
    def CLOUD_BASE_URL(self) -> str:
        return (self.get("cloud_base_url", "") or "").rstrip("/")

    @property
    def PAIRED(self) -> bool:
        return bool(self.get("paired", False))

    @property
    def CLOUD_POLL_TIMEOUT_S(self) -> int:
        return int(self.get("cloud_poll_timeout_s", 35))


# ─── Singleton ────────────────────────────────────────────────────────────────

cfg = Config()

# ─── Backward-compat module-level names ───────────────────────────────────────
# Code that does `from config import X` continues to work unchanged.
# For live-updated values, use `cfg.X` or `cfg.get("x")` directly.

MODEL_PATH            = cfg.MODEL_PATH
CONF_THRESHOLD        = cfg.CONF_THRESHOLD
IOU_THRESHOLD         = cfg.IOU_THRESHOLD
INPUT_WIDTH           = cfg.INPUT_WIDTH
INPUT_HEIGHT          = cfg.INPUT_HEIGHT
CAMERA_FPS            = cfg.CAMERA_FPS
SNAPSHOT_INTERVAL_MS  = cfg.SNAPSHOT_INTERVAL_MS
WEB_HOST              = cfg.WEB_HOST
WEB_PORT              = cfg.WEB_PORT
AI_FOCUS_DURATION_S   = cfg.AI_FOCUS_DURATION_S
AUDIO_DIR             = cfg.AUDIO_DIR
AUDIO_COOLDOWN_S      = cfg.AUDIO_COOLDOWN_S
DANGER_AREA_THRESHOLD = cfg.DANGER_AREA_THRESHOLD
OPENAI_API_KEY        = cfg.OPENAI_API_KEY
OPENAI_MODEL          = cfg.OPENAI_MODEL
OPENAI_TIMEOUT_S      = cfg.OPENAI_TIMEOUT_S
LOG_PATH              = cfg.LOG_PATH
LOG_MAX_LINES         = cfg.LOG_MAX_LINES
PROMPT_SCENE          = cfg.PROMPT_SCENE
PROMPT_QRIS           = cfg.PROMPT_QRIS

RELEVANT_LABELS = {
    "person", "bicycle", "car", "motorcycle", "bus", "truck",
    "dog", "cat", "chair", "bottle", "handbag", "backpack",
}

COCO_LABEL_MAP = {
    0:  "person",       1:  "bicycle",   2:  "car",          3:  "motorcycle",
    4:  "airplane",     5:  "bus",       6:  "train",        7:  "truck",
    14: "bird",         15: "cat",       16: "dog",          17: "horse",
    24: "backpack",     25: "umbrella",  26: "handbag",
    39: "bottle",       56: "chair",     57: "couch",        58: "potted plant",
    62: "tv",           63: "laptop",    64: "mouse",        67: "phone",
}

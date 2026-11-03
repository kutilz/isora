"""
I-Sora SDK — Dynamic configuration
Loaded from /root/config.json at startup; updatable at runtime via companion API.
"""

import os
import json
import threading
import time
from pathlib import Path

from utils import scene_prompt

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
    # ── Camera orientation (persisted across reboots) ─────────────────────────
    # Quarter-turn correction applied to every frame the moment it leaves the
    # sensor: 0 | 90 | 180 | 270, clockwise. The mount angle changes with how
    # the device is worn (chest clip vs. hung the other way round vs. strapped
    # sideways), and a rotated frame silently corrupts everything downstream —
    # left/right in the spoken alert, the ground-contact distance hint, and the
    # collected dataset. Set from the web UI (POST /config), stored here so the
    # device comes back correctly oriented after a power cycle. 180 is applied
    # by the sensor ISP (free); quarter turns rotate in software and swap the
    # frame axes. See utils/orientation.py.
    "camera_rotation":          0,
    "snapshot_interval_ms":     500,
    "web_host":                 "0.0.0.0",
    "web_port":                 8080,
    "ai_focus_duration_s":      5,
    "audio_dir":                "/root/audio",
    "audio_cooldown_s":         2.0,
    "danger_area_threshold":    0.15,
    # ── Distance tiers (per-class coarse near/far + ground hint) ──────────────
    # distance.band() collapses a box into "near"/"far". The near cutoff is
    # per-class (a car must fill more frame than a bottle to count as close);
    # values are FIRST-GUESS area_ratios to calibrate on-device. Unknown labels
    # use distance_near_area_default. A box resting low in the frame (its base
    # near the bottom = on the ground in front) gets up to *_ground_nudge_max
    # shaved off its cutoff, ramping in once the base is below *_ground_nudge_start.
    # *_hysteresis_margin is the half-width of the near/far enter/exit band that
    # stops a boundary-hovering object flapping (and re-announcing) every frame.
    "distance_near_area": {
        "bottle": 0.04, "handbag": 0.05, "backpack": 0.06, "cat": 0.06,
        "dog": 0.10, "chair": 0.12, "person": 0.15, "bicycle": 0.16,
        "motorcycle": 0.18, "car": 0.30, "truck": 0.38, "bus": 0.40,
    },
    "distance_near_area_default":   0.15,
    "distance_ground_nudge_max":    0.25,
    "distance_ground_nudge_start":  0.55,
    "distance_hysteresis_margin":   0.10,
    # ── Detection de-flicker (anti false-positive) ────────────────────────────
    # A detected label must persist in roughly the same spot for this many
    # consecutive frames before it's emitted/announced. Filters YOLO phantom
    # boxes that flicker/teleport on a covered or blurred lens. Set to 1 to
    # disable. detection_max_center_move is the max normalized (0..1) per-frame
    # box-center jump still treated as the "same" object.
    "detection_min_streak":      3,
    "detection_max_center_move": 0.25,
    # ── Detection audio back-off (anti-spam) ──────────────────────────────────
    # A persistent/phantom detection ("orang di depan") announces at most this
    # many times (spaced by audio_cooldown_s), then goes quiet — only an
    # occasional reminder every detection_repeat_remind_s — until the alert
    # changes (different object/position) or disappears. Stops the device getting
    # stuck looping the same alert. Set detection_repeat_limit<=0 to disable.
    "detection_repeat_limit":     3,
    "detection_repeat_remind_s":  30.0,
    # After a user presses a button / issues a command, mute detection audio for
    # this long so the resulting action (mode confirmation, description, repeat)
    # is heard instead of being drowned by detection alerts. The press itself
    # always barges in (flushes the queue) regardless of this window.
    "detection_mute_after_interaction_s": 6.0,
    # ── AI provider ───────────────────────────────────────────────────────────
    # active provider: "openai" | "gemini" | "claude"
    "ai_provider":              "openai",
    "ai_timeout_s":             30,   # a healthy call was measured at 21 s on a phone hotspot
    # After a cloud call runs this many seconds "koneksi internet lambat" is said,
    # once per call (core/ai_engine._ProgressCues). Keep it above the slower
    # normal calls (9-11 s seen on a healthy hotspot) so it stays a real warning.
    "ai_slow_warn_s":           12,
    # OpenAI
    "openai_api_key":           "",
    "openai_model":             "gpt-5.6-terra",
    # Reasoning-capable models think by default (adds latency the same way
    # Gemini's thinkingConfig does — see gemini_adapter.py); keep this low
    # for a scene description that needs no reasoning. One of: none, minimal,
    # low, medium, high, xhigh (not all models support every value).
    "openai_reasoning_effort":  "low",
    "openai_timeout_s":         10,   # kept for backward-compat; ai_timeout_s is used
    # Gemini
    "gemini_api_key":           "",
    "gemini_model":             "gemini-1.5-flash",
    # Claude (Anthropic)
    "claude_api_key":           "",
    "claude_model":             "claude-haiku-4-5-20251001",
    # Sampling temperature for the vision call. 0.0 = as deterministic as the
    # provider allows, which is what a describe button wants: pressing it twice
    # on an unchanged scene should not produce a re-worded world. Reasoning
    # models (gpt-5.6 and friends) reject the parameter outright, so the
    # OpenAI adapter drops it there and the prompt's output contract carries
    # the consistency on its own — see utils/scene_prompt.py.
    "ai_temperature":           0.0,
    # Prompts (runtime-editable)
    # Context-mode scene description. Two verbosity levels, switchable live from
    # the /buttons UI via `scene_verbosity` ("sedang" | "detail"). "detail" is
    # the long, complete description; "sedang" is one short, consistent sentence
    # — far faster to synthesize/play and far more likely to hit the per-word
    # cache (so it gets instant as the vocabulary warms).
    #
    # Both defaults come from utils/scene_prompt.py, which documents WHY they
    # are long: a flat one-liner gave a re-worded answer on every press,
    # described the wall behind a held banknote, and produced the same generic
    # "ada meja dan kursi" in a lab, a lecture hall and a pavement.
    "scene_verbosity": "detail",
    "prompt_scene":         scene_prompt.SCENE_PROMPT_DETAIL,
    "prompt_scene_sedang":  scene_prompt.SCENE_PROMPT_SEDANG,
    # Which prompt pack generation the stored config was written by. Devices
    # provisioned before a pack bump get migrated on load (migrate_prompt_pack).
    "prompt_pack_version":  scene_prompt.PROMPT_PACK_VERSION,
    "prompt_qris": (
        "Baca kode QRIS ini. Sebutkan: nama merchant dan nominal jika ada. "
        "Format: MERCHANT: [nama], NOMINAL: [angka]. "
        "Jika bukan QRIS, jawab: BUKAN QRIS."
    ),
    "log_path":                 "/root/logs",
    "log_max_lines":            500,
    "diag_sample_s":            60,     # utils/diag.py; 0 = no minute samples
    # Keep every photo sent to the AI in /root/captures/debug, with the answers
    # in index.jsonl; nothing is deleted. It can show people, so this stays off
    # by default and is switched on per unit for an evaluation session.
    "debug_save_frames":        False,
    # ── Adaptive power management (utils/power.py) ────────────────────────────
    # thermal_throttle_temp_c is the "hot" rung of the governor's ladder; the
    # warm and critical rungs sit at fixed offsets around it, so this one number
    # tunes the whole response. The device answers heat by doing less work —
    # fewer frames, fewer inferences, no dashboard preview — and never by
    # announcing it. Someone walking with the device strapped on cannot act on
    # a "suhu tinggi" warning, and telling them to power down mid-journey is
    # not an option the product has.
    "thermal_throttle_temp_c":  80.0,
    # Legacy: superseded by the governor's per-tier fps ladder. Kept so an
    # existing /root/config.json and cfg.THERMAL_THROTTLE_FPS still resolve.
    "thermal_throttle_fps":     10,
    # How far below a tier's entry temperature the device must cool before it
    # steps back down. Stops a reading hovering on a boundary from retiming the
    # loop every poll.
    "power_recover_margin_c":   5.0,
    # Quiet-scene downshift: after this many seconds with no detections, no
    # pending command and no recent interaction, drop to power_idle_fps. One
    # busy frame restores the full rate immediately — the event that ends a
    # quiet stretch is exactly the one the user needs to hear about.
    "power_idle_after_s":       20.0,
    "power_idle_fps":           8.0,
    # How long after the last /snapshot fetch the device keeps encoding the
    # dashboard preview. The page polls twice a second, so a few seconds spans
    # normal polling without leaving the encoder running for a closed tab.
    "preview_grace_s":          5.0,
    # ── Boot mode ─────────────────────────────────────────────────────────────
    # Mode the device stands in at power-on: "idle" | "explorer" | "context" |
    # "qris" | "last". Default "idle" — the neutral state where the device is
    # on, reachable and quiet. Booting straight into explorer means it starts
    # narrating before anyone has asked it to, while it is still in a bag or
    # being handed over. "last" resumes whatever mode it was switched off in.
    "boot_mode":                "idle",
    # Written on every mode switch so boot_mode="last" has something to read.
    "last_mode":                "explorer",
    "watchdog_timeout_s":       5.0,
    # ── SoC hardware watchdog (utils/hw_watchdog.py) ─────────────────────────
    # The in-process watchdog above cannot survive the failure this device
    # actually hits: a camera/NPU teardown that blocks inside a C call holds
    # the GIL, so every Python thread — the watchdog included — stops. Only
    # silicon can recover that. Confirmed on a MaixCAM Lite: /dev/watchdog
    # exists, arms on open, and really does reset the board.
    # DEFAULT OFF, deliberately. Arming an auto-reset that nobody has watched
    # run turns a rare hang into a possible reboot loop, which is worse. Switch
    # it on per unit after observing one run with it armed.
    "hw_watchdog_enabled":      False,
    "hw_watchdog_timeout_s":    60,
    "hw_watchdog_pet_s":        2.0,
    # How stale the AI-loop heartbeat may get before petting stops. Generous:
    # one tick legitimately covers a cloud describe, so this must sit well
    # above the slowest healthy tick or a busy device would reset itself.
    "hw_watchdog_stale_s":      45.0,
    # Same signal for the app supervisor (system/supervise.sh, via
    # utils/liveness.py), which only restarts the app and so is always on. The
    # supervisor adds its own 30 s on top before it kills.
    "liveness_stale_s":         45.0,
    # MaixPy's UART CommProtocol listener ([Default CommListener]), started by
    # `import maix`. It polls UART0 for MaixVision/MCU protocol frames, which
    # nothing on this device sends, and inside the app it measured ~30% of the
    # single core even in idle — enough load that the WiFi driver starved
    # (DNS failures, cloud describe timeouts). Off unless something needs it.
    "maix_comm_listener":       False,
    # ── Hardware buttons (active-low to GND; internal pull-up, no resistor) ───
    # The GPIO listener enables PULL_UP, so any free standard GPIO works — wire
    # each button: leg1 → pad, leg2 → GND. Pads that can NEVER work:
    #   A14 — onboard user LED, claimed as output by the kernel led driver;
    #   P18–P23 — SDIO1 bus of the internal AIC8800 WiFi module (mmc1/wifi-sd);
    #   A26 — WiFi EN on the WiFi board variant (button there toggles WiFi).
    # MODE button pad ("A28" recommended; "" or -1 = disabled). Short press
    # cycles mode / repeats URL during onboarding; long press = web address / ack.
    "button_pin_mode":          "A28",
    # ACTION button pad ("A29" recommended; "" or -1 = disabled). Short press
    # captures on demand (describe / QRIS scan) — in explorer it switches online
    # navigation on/off instead; long press repeats last result.
    # Safe alternates: A22–A25 (only when SPI4/eMMC is unused).
    "button_pin_action":        "A29",
    # Speaker volume (0-100); read by AudioManager on every play
    "audio_volume":             80,
    # ── Volume mode (hold MODE + ACTION together) ────────────────────────────
    # How long both buttons must be held together before volume mode opens.
    # Long enough that a clumsy two-finger grab is not a chord, short enough
    # that it is not a wait.
    # MUST stay above button_longpress_s. At the old 0.6s the chord fired
    # BEFORE a long press could complete, so any long press where a finger
    # brushed the second pad opened volume mode instead — and the chord eats
    # the release, so the long press the user wanted never happened at all.
    "button_chord_hold_s":      1.5,
    # Volume mode closes itself this long after the last step, so the buttons
    # are never left in a state the user has to remember to leave.
    "volume_mode_timeout_s":    5.0,
    # Points per press. 10 spans the useful range in 8 taps.
    "volume_step":              10,
    # Floor and ceiling for BUTTON-driven volume. Silence stays reachable from
    # /config, never from the buttons: audio is the only channel a blind user
    # has, and a device muted from the outside of the web UI cannot tell them
    # how to get it back.
    "volume_button_min":        20,
    "volume_button_max":        100,
    # Auth: device token (auto-generated on first boot if empty)
    "device_token":             "",
    # CORS: list of allowed origins for dashboard. Empty list = same-origin only.
    # Every page that talks to the device is served BY the device, and the
    # Android app is not a browser, so nothing needs cross-origin access. With
    # ["*"] any web page opened on a phone on the same WiFi could read
    # /snapshot — the camera. Units that still carry the old ["*"] default are
    # moved off it by migrate_cors().
    "cors_allowed_origins":     [],
    # Auth: require token on POST mutate endpoints (False = legacy/dev-only)
    "auth_required":            True,
    # Settings autosave (UI hint; backend always persists immediately)
    "autosave_enabled":         True,
    # QRIS verification mode: "online" | "offline" | "hybrid"
    "qris_mode":                "hybrid",
    # Maximum acceptable QRIS nominal in IDR before requiring extra confirm
    "qris_nominal_warn_cap":    1_000_000,
    # ── Mode scan bayar: banknotes + QRIS on alternating frames ───────────────
    # (modes/pay_mode.py). The banknote model is YOLO26n trained on notes held
    # in the hand, converted to a cv181x cvimodel (INT8, BF16 detection head)
    # whose raw head is read by MaixPy's YOLOv8 decoder — see
    # tools/money_model/README.md. A unit without the file still scans QRIS.
    "money_model_path":         "/root/models/uang_yolo26n.mud",
    # 0.5 rather than the 0.4 that scored best on the test split: a wrong
    # denomination said with confidence costs a blind user money; a note that
    # takes another half-second to be named does not.
    "money_conf_threshold":     0.5,
    # Finds a QR code as an object for the direction guide (utils/qr_guide).
    # MaixPy's own QR model; written to /root/models by hand, not by deploy.py.
    "qr_model_path":            "/root/models/yolov8_qr_det_320x224.mud",
    "qr_conf_threshold":        0.4,
    # Banknote-look frames in a row before a note is named (each look is every
    # other frame), how long it must be out of view to count as put down, and
    # the least time between two namings of the same value.
    "money_min_streak":         3,
    "money_gone_s":             1.5,
    "money_repeat_gap_s":       4.0,
    # The same, for a QR code (one decode is enough to be sure of it).
    "qris_gone_s":              4.0,
    "qris_repeat_gap_s":        10.0,
    # API key encryption lock — when True, web UI cannot overwrite
    # encrypted keys. Unlock procedure: tools/unlock_keys.py on device.
    "api_keys_locked":          False,
    # TTS hybrid: synthesize dynamic text via gTTS and cache on device
    "tts_enabled":              True,
    "tts_cache_dir":            "/root/audio/tts_cache",
    # Which cloud voice renders free-form speech (scene descriptions, QRIS
    # results). "auto" = openai when a key is configured, else gtts.
    #
    # DEFAULT IS gtts, on accent, not on speed. OpenAI's /v1/audio/speech is the
    # faster path on paper — it answers in raw PCM, so nothing has to be decoded
    # by ffmpeg (a flat 1.2-1.8 s per sentence on this board) — but its voices
    # read Indonesian with an audible English accent, which for a user who only
    # has the audio is a worse trade than a second of latency. Set "openai" only
    # with tts_openai_model="gpt-4o-mini-tts" and a tts_openai_instructions that
    # pins the accent, and listen to it before leaving it on.
    "tts_provider":             "gtts",   # "auto" | "gtts" | "openai"
    "tts_openai_model":         "gpt-4o-mini-tts",
    "tts_openai_voice":         "alloy",
    # Only gpt-4o-mini-tts honours this; tts-1/tts-1-hd ignore it.
    "tts_openai_instructions":  ("Bacakan dalam Bahasa Indonesia dengan logat "
                                 "Indonesia yang natural, tenang, dan jelas. "
                                 "Jangan memakai aksen Inggris."),
    "tts_openai_timeout_s":     15.0,
    # How long to wait on one gTTS render before giving up on it.
    "tts_gtts_timeout_s":       20.0,
    # A gTTS render still unanswered after this many seconds gets a second
    # request racing it on a fresh connection (0 = never). On a phone's mobile
    # data a stalled first request is what cut descriptions off mid-sentence.
    "tts_gtts_hedge_s":         4.0,
    # Per-word TTS cache (context mode). Scene sentences are near-unique but
    # reuse a small Indonesian vocabulary, so caching audio per word lets a
    # fully-seen sentence play with zero network. A missing word never drops a
    # word ("ompong") — the whole sentence is spoken via gTTS and the missing
    # words are warmed in the background for next time.
    "word_cache_enabled":       True,
    "word_cache_dir":           "/root/audio/word_cache",
    # Smoothing for concatenated word audio (each gTTS word carries its own
    # head/tail silence, which makes a naive concat sound choppy):
    #   trim each word's silence, then a NEGATIVE gap overlaps adjacent words to
    #   tighten them. All live-tunable via /config to taste.
    "word_cache_gap_ms":        -10,   # <0 = overlap+crossfade (smoother), >0 = inserted silence
    # Cap (in words) on sentence length eligible for concat mode. Long
    # free-form text (e.g. "detail" scene descriptions) loses sentence-level
    # prosody when spliced word-by-word, so past this length we speak one
    # fluent gTTS sentence instead. 0 disables the cap. 12 comfortably covers
    # short/"sedang"-style phrases while routing longer ones to synth.
    "word_cache_max_words":     12,
    "word_cache_trim_enabled":  True,
    "word_cache_trim_threshold": 600,  # |amplitude| below this counts as silence
    "word_cache_trim_margin_ms": 8,    # keep this much real audio around the signal
    "word_warm_per_call":       8,     # words warmed (gTTS) per describe (gentle on the 1-core box)
    "word_warm_gap_s":          0.5,   # pause between background warms (avoid load spikes)
    # Sentence chunks a scene description is streamed in. gTTS time scales with
    # text length (measured on-device: 155 chars -> 5.3 s, 89 chars -> 1.8 s),
    # so speaking the first sentence while the rest still synthesizes cuts the
    # silence after the chime roughly in half. 1 disables streaming.
    "scene_stream_chunks":      3,
    # ── Online navigation (explorer + ACTION; modes/scan_narrator.py) ────────
    # Seconds from one photo to the next. A floor, not a promise: the next
    # photo also waits for the previous sentence to finish playing, so the
    # narrator never talks over itself. Settable from /buttons and the cloud
    # app; clamped to 3-60 at the read site (Config.SCAN_INTERVAL_S).
    "scan_interval_s":          8,
    # A result that lands this long after its photo is dropped unspoken: at
    # walking pace the user is metres past where it was taken. Measured on
    # isora-88dd: the short prompt answers in 2.2-3.0 s.
    "scan_stale_s":             6,
    # After a failed call, wait at least this long before the next one, so a
    # dead hotspot is not hammered every few seconds. The failure is spoken
    # once per outage, not once per attempt.
    "scan_retry_s":             15,
    "prompt_scan":              scene_prompt.SCENE_PROMPT_SCAN,
    # I2C battery HAT: enabled only after manual probe via /i2c-probe endpoint
    "i2c_battery_enabled":      False,
    # Companion redesign (handoff §4.3) — audio playback preference
    # "chime"  → only pre-recorded chimes, skip TTS
    # "speech" → only TTS, skip chimes
    # "both"   → chime then TTS (legacy behavior)
    "audio_mode":               "both",
    # ── Brand identity (white-label toggle: "auralai" | "isora") ──────────────
    # Same software, different branding. Controls the spoken boot/ready greeting
    # (which audio set plays) and the name shown in the /buttons web UI. Flipped
    # live from the hidden long-press on the /buttons logo (POST /brand). The
    # greeting sets live in /root/audio/brand/<brand>/{menyala,siap_digunakan}.
    # {wav,pcm} and are copied over the canonical isora_menyala.* /
    # isora_siap_digunakan.* names (which main.py + AudioManager resolve) on a
    # switch. Upstream SDK default is "auralai"; I-Sora ships pinned to "isora".
# A field unit can still be pinned to a
    # brand in its /root/config.json (e.g. the I-Sora demo unit → "isora").
    "brand":                    "isora",
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
    # Friendly device name; "" → auto "isora-<mac-suffix>" (see utils/identity).
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
    # ── Cloud pairing (isora web hub) ───────────────────────────────────────
    # When True, once online the device registers with the cloud relay, speaks a
    # short pairing code, and pulls config pushed from the web. Offline-safe:
    # if the cloud is unreachable it falls back to the local spoken-URL setup.
    "cloud_enabled":            True,
    # Base URL of the deployed web hub (Vercel). Override for local testing, e.g.
    # "http://<your-pc-ip>:3000". Production: your isora-smartglasses.vercel.app / *.vercel.app URL.
    "cloud_base_url":           "https://isora-smartglasses.vercel.app",
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
    # ── Auto-update (core/updater.py) ───────────────────────────────────────
    # Check GitHub for a newer signed release this often, download it in the
    # background, and switch at the next boot or after 10 quiet minutes in idle
    # mode. A release that does not come up healthy is rolled back. Inert until
    # `tools/run.py --autostart` has installed /etc/isora/release.py.
    "auto_update":              True,
    "update_check_hours":       24,
    # ── Mode PIMNAS (event profile; server/static/pimnas.html) ──────────────
    # One switch for a live demo on a venue network nobody can trust. While on:
    # no update is fetched or switched to, a describe gives up after
    # event_ai_timeout_s instead of ai_timeout_s, and when it fails the device
    # reads out what the nav YOLO sees (context mode keeps that model loaded
    # for exactly this). Data collection / benchmark / stress refuse to start.
    # Settable only from the LAN operator page, never from the cloud push.
    "event_mode":               False,
    "event_ai_timeout_s":       10,
    # Sentences typed on the operator page, rendered once, played offline.
    "speech_presets_dir":       "/root/audio/pimnas_presets",
}


def select_scene_prompt(verbosity: str, sedang: str, detail: str) -> str:
    """Pick the scene prompt for the given verbosity. Anything that isn't
    exactly "sedang" falls back to the detailed prompt (safe default — never go
    terse by accident)."""
    return sedang if verbosity == "sedang" else detail


def migrate_prompt_pack(data: dict) -> dict:
    """Return the keys that must change so `data` carries the current prompts.

    Config._load merges the saved file OVER _DEFAULTS, so a unit provisioned
    before a prompt-pack bump keeps its old prompt forever — a new default is
    otherwise invisible in the field, which is exactly how the pilot units
    ended up still running the flat one-line prompt long after it was replaced
    in the repo. Same trap the openai adapter documents for openai_model.

    Only prompts this project itself shipped are replaced (scene_prompt's
    legacy tables). A prompt the operator wrote in the dashboard is left
    untouched no matter how old the pack version is — their edit outranks our
    default, and silently reverting it would look like the field simply does
    not save.

    Returns {} when nothing needs to change, so the caller can skip the write.
    """
    try:
        stored_ver = int(data.get("prompt_pack_version", 0))
    except (TypeError, ValueError):
        stored_ver = 0
    if stored_ver >= scene_prompt.PROMPT_PACK_VERSION:
        return {}

    changes: dict = {"prompt_pack_version": scene_prompt.PROMPT_PACK_VERSION}
    if scene_prompt.is_legacy_scene_prompt(data.get("prompt_scene", "")):
        changes["prompt_scene"] = scene_prompt.SCENE_PROMPT_DETAIL
    if scene_prompt.is_legacy_sedang_prompt(data.get("prompt_scene_sedang", "")):
        changes["prompt_scene_sedang"] = scene_prompt.SCENE_PROMPT_SEDANG
    return changes


def migrate_cors(data: dict) -> dict:
    """Move a unit off the wide-open CORS default it was provisioned with.

    Config._load merges the saved file over _DEFAULTS and save() writes every
    key, so each unit set up before the default changed still carries ["*"]
    in config.json. Nothing in this project ever needed it (see the default's
    comment), so the old default is treated as unset. Any other list is an
    operator's choice and is left alone.
    """
    if data.get("cors_allowed_origins") == ["*"]:
        return {"cors_allowed_origins": []}
    return {}


class Config:
    """
    Thread-safe configuration backed by /root/config.json.
    Call cfg.update(dict) to change values at runtime — persisted to disk.
    """

    def __init__(self):
        self._lock = threading.RLock()
        # Separate from _lock: _lock guards the dict (held briefly), _save_lock
        # guards the write+replace to disk (held across flash I/O). Sharing one
        # would make every reader wait out an fsync.
        self._save_lock    = threading.RLock()
        self._save_pending = False
        self._data: dict = dict(_DEFAULTS)
        self._load()

    # ─── Persistence ──────────────────────────────────────────────────────────

    def _load(self):
        try:
            with open(_CONFIG_PATH) as f:
                loaded = json.load(f)
            # Migrate off `loaded`, NOT off the merged dict: _DEFAULTS already
            # carries the current prompt_pack_version, so a merged dict always
            # looks up to date and every stale unit in the field would keep its
            # old prompt forever — the exact failure the migration exists to fix.
            changes = migrate_prompt_pack(loaded)
            changes.update(migrate_cors(loaded))
            with self._lock:
                self._data.update(loaded)
                self._data.update(changes)
            # Persist outside the lock — save() takes it again, and a prompt
            # migration that only lived in RAM would re-run on every boot.
            if changes:
                self.save()
        except FileNotFoundError:
            self._write_defaults()
        except Exception:
            # Corrupt/unreadable config: preserve it as .corrupt for recovery
            # instead of letting the next save() silently overwrite it (which
            # would permanently lose device_token, pairing, and encrypted keys).
            backed_up = False
            try:
                if _CONFIG_PATH.exists():
                    os.replace(_CONFIG_PATH, str(_CONFIG_PATH) + ".corrupt")
                backed_up = True
            except Exception:
                backed_up = False
            # Only regenerate defaults once the original is safely out of the
            # way. If the rename itself failed (read-only mount after an fsck,
            # EACCES, or the path is a directory) then writing defaults here
            # would destroy the only copy of device_token and every
            # *_api_key_enc — precisely the loss the backup exists to prevent.
            # Run on the in-memory defaults __init__ already loaded and leave
            # the file alone; an operator can still recover it by hand.
            if backed_up:
                self._write_defaults()

    def _write_defaults(self):
        # Same tmp+fsync+replace durability as save(): a half-written defaults
        # file is exactly as unreadable as the corrupt one it replaces, and
        # would send the next boot down this same path.
        try:
            _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = str(_CONFIG_PATH) + ".tmp"
            with open(tmp, "w") as f:
                json.dump(_DEFAULTS, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, _CONFIG_PATH)
        except Exception:
            pass

    def save(self):
        """Persist current config to disk atomically (tmp file + os.replace).

        A plain truncate-then-write leaves a half-written file if power is cut
        mid-save; _load() then falls back to defaults and the next save makes
        the loss permanent. Writing to a temp file and atomically replacing
        guarantees the on-disk config is always a complete, valid document.

        TWO writers, one tmp path. Every caller used to write the SAME
        "config.json.tmp": a volume step saving from the button thread while
        the web UI saved from an HTTP thread had one process os.replace() a
        file the other was still streaming into, publishing a truncated
        document as the live config. That costs device_token and every
        encrypted API key on the unit — recoverable only by re-provisioning.
        The tmp name is now unique per writer, and _save_lock serializes the
        replace so the last writer always publishes a whole document.
        """
        with self._lock:
            data = dict(self._data)
        tmp = "%s.tmp.%d.%d" % (_CONFIG_PATH, os.getpid(),
                                threading.get_ident())
        with self._save_lock:
            try:
                with open(tmp, "w") as f:
                    json.dump(data, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, _CONFIG_PATH)
            except Exception:
                try:
                    os.unlink(tmp)
                except Exception:
                    pass

    def save_async(self, delay_s: float = 1.0):
        """Coalesced background save — for callers on a latency-critical thread.

        A button press must never wait on flash. Repeated calls inside `delay_s`
        collapse into one write, so mashing the volume chord cannot turn into a
        burst of concurrent saves (the exact pattern that used to race on the
        shared tmp path above).
        """
        with self._save_lock:
            if self._save_pending:
                return
            self._save_pending = True

        def _run():
            try:
                time.sleep(delay_s)
            except Exception:
                pass
            with self._save_lock:
                self._save_pending = False
            self.save()

        threading.Thread(target=_run, daemon=True, name="CfgSave").start()

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
    def CAMERA_ROTATION(self) -> int:
        """Frame rotation in clockwise degrees, snapped to 0/90/180/270.

        Normalized at the READ site as well as in the POST /config handler: the
        cloud config push writes straight into cfg without going through that
        validation, and a bogus value here would be handed to image.rotate()
        on the AI loop's hot path.
        """
        from utils.orientation import normalize_rotation
        return normalize_rotation(self.get("camera_rotation", 0))

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
        # Every adapter reads its socket timeout here rather than doing its own
        # int() on the raw value. ai_timeout_s is settable via POST /config and
        # the cloud config push and neither validates it; a bare ValueError
        # raised inside an adapter would bypass ai_engine's `except AdapterError`
        # and leave the user with silence instead of the "AI error" cue.
        try:
            t = int(self.get("ai_timeout_s", 15))
        except (TypeError, ValueError):
            t = 15
        t = max(1, min(120, t))
        if self.EVENT_MODE:
            # On a stage a silent 15 s reads as a dead device. Give up sooner
            # and let ai_engine's offline fallback speak instead.
            t = min(t, int(self._clamped(self.get("event_ai_timeout_s", 10),
                                         10.0, 4.0, 60.0)))
        return t

    @property
    def EVENT_MODE(self) -> bool:
        return self.get("event_mode", False) is True

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
        # Clamped at the READ site, not only in the POST /config handler: this
        # value is passed straight to player.volume() for a speaker sitting in a
        # blind user's ear, and the cloud config push (cloud.py
        # ALLOWED_CONFIG_KEYS) writes audio_volume without going through that
        # handler's validation at all.
        try:
            vol = int(self.get("audio_volume", 80))
        except (TypeError, ValueError):
            return 80
        return max(0, min(100, vol))


    @property
    def AI_TEMPERATURE(self) -> float:
        """Sampling temperature for the vision call, clamped to 0.0-2.0.

        Clamped at the READ site as well as in POST /config: the cloud config
        push writes straight into cfg with no validation, and a junk value here
        would be sent verbatim to three different provider APIs — each of which
        answers a bad temperature with an HTTP 400, i.e. a describe press that
        fails with "gagal menganalisis" and no hint why.
        """
        try:
            t = float(self.get("ai_temperature", 0.0))
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(2.0, t))

    @property
    def PROMPT_SCENE(self) -> str:
        return select_scene_prompt(
            self.get("scene_verbosity", "detail"),
            self.get("prompt_scene_sedang", _DEFAULTS["prompt_scene_sedang"]),
            self.get("prompt_scene", _DEFAULTS["prompt_scene"]),
        )

    @property
    def PROMPT_SCAN(self) -> str:
        return self.get("prompt_scan", _DEFAULTS["prompt_scan"]) or _DEFAULTS["prompt_scan"]

    @staticmethod
    def _clamped(raw, default: float, lo: float, hi: float) -> float:
        try:
            v = float(raw)
        except (TypeError, ValueError):
            return default
        if v != v:                       # NaN
            return default
        return max(lo, min(hi, v))

    @property
    def SCAN_INTERVAL_S(self) -> float:
        """Online-navigation photo interval, clamped to 3-60 s.

        Clamped here and not only in POST /config: the cloud config push writes
        straight into cfg, and a 0 would turn the narrator into a loop of
        back-to-back cloud calls on a single-core board.
        """
        return self._clamped(self.get("scan_interval_s", 8), 8.0, 3.0, 60.0)

    @property
    def SCAN_STALE_S(self) -> float:
        return self._clamped(self.get("scan_stale_s", 6), 6.0, 2.0, 30.0)

    @property
    def SCAN_RETRY_S(self) -> float:
        return self._clamped(self.get("scan_retry_s", 15), 15.0, 3.0, 300.0)

    @property
    def PROMPT_QRIS(self) -> str:
        return self.get("prompt_qris", _DEFAULTS["prompt_qris"])

    @property
    def AUTH_REQUIRED(self) -> bool:
        return bool(self.get("auth_required", True))

    @property
    def CORS_ALLOWED_ORIGINS(self) -> list:
        v = self.get("cors_allowed_origins", [])
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
    def BRAND(self) -> str:
        """White-label brand: "auralai" | "isora". Anything else → "isora"."""
        b = self.get("brand", "isora")
        return b if b in ("auralai", "isora") else "isora"

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

# ─── Single source of truth for the nav object set (T6 / DRY) ─────────────────
# COCO label → Indonesian spoken id. This is the ONE canonical map; every other
# place that needs the object set (RELEVANT_LABELS here, tools/generate_audio.py
# OBJECTS, and audio_manager._LABEL_ID) must DERIVE from this so they can't drift.
NAV_OBJECTS = {
    "person":     "orang",
    "motorcycle": "motor",
    "car":        "mobil",
    "bicycle":    "sepeda",
    "bus":        "bus",
    "truck":      "truk",
    "dog":        "anjing",
    "cat":        "kucing",
    "chair":      "kursi",
    "bottle":     "botol",
    "handbag":    "tas",
    "backpack":   "ransel",
}

# Derived, never hand-edited — keeps the announced set in lock-step with NAV_OBJECTS.
RELEVANT_LABELS = set(NAV_OBJECTS.keys())

# Detected but never announced, for now: at a live demo a mislabelled person must
# not be called "anjing" (PIMNAS, Nov 2026). Empty this set to bring them back;
# their WAVs stay planned. Mirrored in web/lib/sim/constants.ts.
MUTED_NAV_LABELS = {"dog", "cat"}

COCO_LABEL_MAP = {
    0:  "person",       1:  "bicycle",   2:  "car",          3:  "motorcycle",
    4:  "airplane",     5:  "bus",       6:  "train",        7:  "truck",
    14: "bird",         15: "cat",       16: "dog",          17: "horse",
    24: "backpack",     25: "umbrella",  26: "handbag",
    39: "bottle",       56: "chair",     57: "couch",        58: "potted plant",
    62: "tv",           63: "laptop",    64: "mouse",        67: "phone",
}

# AuralAI SDK — Changelog

---

## [Phase 4 — Companion Redesign] — 2026-05-21

Implements the `design_handoff_auralai_redesign/` package: split the operator
dashboard into three audience-specific interfaces plus a first-time setup
wizard, all WCAG 2.1 AA compliant.

### New routes

- `GET /`                       — Companion dashboard for pendamping (guru SLB,
                                  keluarga). Redirects to `/setup` when
                                  `setup_completed` is false.
- `GET /admin`                  — Operator/dev dashboard. Wraps the companion
                                  view + adds AdminRibbon, Debug Overlay,
                                  DevSidebar with log tail + quick actions.
- `GET /guide`                  — Public scroll-page panduan (no auth). Hero
                                  + Storyboard + Hardware + Audio + Audio
                                  preference picker.
- `GET /setup`                  — 4-step first-time wizard (power → wifi →
                                  AI key → handover checklist).
- `GET /admin/legacy`           — Original operator dashboard
                                  (`static/index.html`), kept reachable.
- `GET /tokens.css`             — Design tokens (single source of truth).
- `GET /audio/chimes/manifest.json`
                                — Lists pre-recorded chime WAVs; frontend
                                  hides the "Putar" column when empty.
- `GET /assets/manifest.json`   — Lists available photo assets; frontend
                                  swaps SVG mockups for photos when files
                                  exist in `/root/assets/`.
- `GET /assets/<name>`          — Static asset serving with mime guess +
                                  immutable cache headers.
- `GET /history?date=today`     — Activity feed (parsed from log buffer).
- `GET /app/<...>`              — Hashed JS/CSS chunks from the Vite build.

### New config keys

- `audio_mode`: `"chime"` | `"speech"` | `"both"` (default `"both"`).
  AudioManager `_play_task` now honors this: chime mode drops TTS fallback,
  speech mode bypasses pre-recorded chimes.
- `admin_role_token`: optional separate token for admin role. Empty =
  device_token grants admin too.
- `setup_completed`: bool gate for first-time wizard redirect.
- `assets_dir`: filesystem path for `/assets/<name>` serving (default
  `/root/assets`).

### New status fields

`GET /status` now returns:

- `battery` (int 0..100 or `null` when no calibrated HAT)
- `wifi_signal` (0..4 bars from `/proc/net/wireless`)
- `wifi_ssid` (`iwgetid -r`)
- `temperature` (CPU °C)
- `last_caption` (`{text, time_iso, priority}`)
- `audio_mode`
- `setup_completed`

### UI build pipeline

- **New** `device/server/src/` — Vite + Preact + TypeScript source for the
  four new pages. Builds into `device/server/static/app/` which is committed
  (device has no Node.js). Total runtime ~10 KB gz shared chunk + 0.5-9 KB
  gz per page. Dev: `cd device/server/src && npm install && npm run build`.
- **New** `device/server/static/tokens.css` — design tokens, served at
  `/tokens.css` and linked from every entry HTML. Edit-and-reload, no
  rebuild needed.
- **New** `device/server/src/i18n/{id,en}.json` — id.json populated; en.json
  is a stub. See `device/server/src/README.md` for the 3-step EN swap-in.

### Audio manager

- `current_text` companion property `last_caption` now exposes the most
  recent caption with timestamp + priority, persists after playback ends.
- `_play_task` checks `cfg.AUDIO_MODE` per task — change the preference via
  `POST /config { "audio_mode": "..." }` and the next task respects it.

### Accessibility (WCAG 2.1 AA)

- A11y bar on every new page: high-contrast / large-type / reduced-motion,
  persisted to localStorage.
- Skip-link "Lewati ke konten utama" first focusable element.
- `aria-live="polite"` on StatusBanner + LiveView last-caption.
- `role="radiogroup"` + `role="radio"` for mode + audio-mode pickers.
- Hit-targets ≥ 48 px via `--hit` token.
- Keyboard shortcuts 1/2/3 mode, +/- volume, ? help. Skipped when an input
  has focus.
- `<html lang="id">` set at runtime via lib/i18n.

### Files

- `device/config.py` — `_DEFAULTS` + typed properties
- `device/server/web_server.py` — new routes
- `device/core/orchestrator.py` — `get_status()` + telemetry helpers
- `device/core/audio_manager.py` — `last_caption` + audio_mode gating
- `device/server/static/tokens.css` (new)
- `device/server/static/app/` (new — built artifact)
- `device/server/src/` (new — Preact source)
- `design_handoff_auralai_redesign/` (vendored handoff package)

---

## [Phase 3] — 2026-05-14

### AI Vision API Adapters

- **New: `device/adapters/` package** with unified `AIAdapter` base class and three provider implementations:
  - `OpenAIAdapter` — Chat Completions with `image_url` (base64 inline); `gpt-4o-mini` default
  - `GeminiAdapter` — `generateContent` REST v1beta with `inlineData`; `gemini-1.5-flash` default
  - `ClaudeAdapter` — Anthropic Messages API with `image` content blocks; `claude-haiku-4-5` default
  - All adapters share `describe_scene()`, `scan_qris()`, and `test_connection()` interface
  - Factory function `get_adapter(provider, cfg)` selects adapter based on active provider
- **Updated `device/core/ai_engine.py`** — replaced hardcoded OpenAI calls in `trigger_scene_description()` and `trigger_qris_scan()` with `get_adapter(cfg.AI_PROVIDER, cfg)`; no structural changes to the inference pipeline

### Config Changes

- **Updated `device/config.py`**:
  - New keys: `ai_provider` ("openai"/"gemini"/"claude"), `ai_timeout_s`, `gemini_api_key`, `gemini_model`, `claude_api_key`, `claude_model`
  - `prompt_scene` and `prompt_qris` moved from class-level string constants → runtime-editable config keys (backed by `/root/config.json`)
  - New typed properties: `AI_PROVIDER`, `AI_TIMEOUT_S`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `CLAUDE_API_KEY`, `CLAUDE_MODEL`, `PROMPT_SCENE`, `PROMPT_QRIS`

### Web UI — AI Settings

- **New `GET /ai-settings`** — returns active provider, model names, key presence hints (last 4 chars), and prompts; API keys are never returned in full
- **New `POST /ai-settings`** — saves provider/model/key/prompt changes; empty key fields are ignored (no accidental key erasure)
- **New `POST /ai-settings/test`** — tests live connectivity to the configured adapter using a minimal text-only call
- **Updated `device/server/static/index.html`** — "AI Settings" button in controls bar; full settings modal with provider selector tabs, model dropdowns, masked API key inputs, editable prompts, test button, and save/cancel
- **Updated `device/server/static/style.css`** — styles for AI settings modal, provider tab buttons, key hint, test result badge

### Bug Fixes

- **`device/utils/health.py` — I2C battery HAT probing**: probes `/dev/i2c-1`/`/dev/i2c-2` at addresses 0x36/0x40 on import; `battery_hat_present()` and `battery_info()` return empty dict silently if no HAT is found — no more `OSError` at startup and battery audio warnings are disabled automatically
- **`device/core/audio_manager.py` — `player.stop()` AttributeError**: `_play_pcm()` now catches `AttributeError` separately from other exceptions; when `stop()` is missing the method returns immediately so the higher-priority task starts without waiting for the full PCM deadline
- **`device/core/audio_manager.py` — `_current_text` tracking**: new `current_text` property (thread-safe) exposes the text currently being played; set on `_play_task` entry, cleared on exit
- **`device/core/orchestrator.py` — `audio_text` in status**: `get_status()` now includes `"audio_text"` from `audio_manager.current_text` so the `/status` endpoint delivers the playing text without the removed `pop_audio()` deque
- **`device/server/web_server.py` — simplified `_serve_status()`**: removed the now-redundant `pop_audio()` call; `audio_text` arrives directly from `get_status()`
- **`device/server/static/dashboard.js` — removed Web Speech API**: `showAudioText()` is now a pure visual log update; `window.speechSynthesis` calls removed entirely; device speaker is the only audio output

---

## [Phase 2] — 2026-05-13

### Standardized Benchmark Suite

- **`device/benchmark/t1_latency.py`** — End-to-End Latency: measures cam/infer/post/queue stages; p95 < 300 ms to pass; score 0–100
- **`device/benchmark/t2_accuracy.py`** — Detection Accuracy: recall/precision on `/root/test_images/`; critical recall ≥ 95%; skips gracefully if no dataset
- **`device/benchmark/t3_audio.py`** — Audio Priority: simulates CRITICAL→LOW interrupt (must succeed within 150 ms); PriorityQueue ordering; cooldown isolation
- **`device/benchmark/t4_stability.py`** — Hardware Stability: full pipeline endurance for configurable duration; FPS ≥ 15 and zero crashes to pass; per-minute snapshots
- **`device/benchmark/report.py`** — Safety & Reliability Index: weighted sum T1×35% + T2×30% + T3×20% + T4×15%; grades A/B/C/D/F; Indonesian recommendations
- **`device/benchmark/run_all.py`** — CLI entry point; `--tests`, `--t1-frames`, `--t4-duration`, `--report-only`; live progress to `/tmp/bench_suite_progress.json`
- **`device/server/web_server.py`** — added `BenchmarkSuiteRunner` class and `/suite/start`, `/suite/stop`, `/suite/progress`, `/suite/report` endpoints

---

## [Phase 1] — 2026-05-12

### Core Rewrite — Real Hardware Integration

#### `device/config.py`

- Full rewrite as thread-safe `Config` singleton backed by `/root/config.json`
- `cfg.update(mapping)` persists to disk; all config keys runtime-updatable
- Backward-compat module-level aliases (`from config import X` still works)

#### `device/core/orchestrator.py`

- Event-driven state machine replacing polling loop
- `switch_mode()` releases/reloads NPU model based on `_YOLO_MODES`
- GPIO hardware button listener (falling-edge, 0.3 s debounce) via `cfg.button_pin_mode`
- Thermal throttle callbacks (`_on_thermal_throttle`, `_on_thermal_recover`)
- `_mode_event` (threading.Event) for zero-latency mode-change wakeup in AI loop

#### `device/core/ai_engine.py`

- NPU inference via `maix.nn.YOLO11`
- `release_model()` / `reload_model()` for mode-switch memory management
- `release()` / `reload()` as watchdog restart functions
- Single auto-recover on camera `RuntimeError`
- Watchdog heartbeat on every successful pipeline tick

#### `device/core/audio_manager.py`

- Non-blocking `threading.PriorityQueue` with levels CRITICAL(0)/HIGH(1)/NORMAL(2)/LOW(3)
- `_interrupt` event for immediate higher-priority preemption
- Cooldown map per label; per-priority stable ordering via sequence counter
- WAV → PCM s16le 48 kHz conversion via ffmpeg (cached)

#### `device/utils/health.py`

- Added `HealthMonitor` daemon: polls every 5 s; fires `on_throttle`/`on_recover` callbacks

#### `device/utils/logger.py`

- Structured JSON logging: `{"ts":…, "level":…, "module":…, "msg":…}`

#### `device/core/watchdog.py` (new)

- Heartbeat-based watchdog; `max_misses × check_interval_s` before `restart_fn()` is called

#### `device/main.py`

- Wires Watchdog, HealthMonitor, Orchestrator, WebServer together

#### `device/server/web_server.py`

- `_handle_config()` now calls `cfg.update(data)` (was a no-op)
- `pop_audio()` stub on Orchestrator for backward-compat (returns None)

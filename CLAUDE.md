# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**I-Sora** ("Melihat dengan Suara") — assistive smart glasses for blind/low-vision users in Indonesia. A **Sipeed MaixCAM** device recognizes surroundings (YOLO object detection, scene description, QRIS) and speaks them in Indonesian.

I-Sora is a **rebrand of AuralAI** — *the same software*, different branding, plus its own hardware. The rebrand is **complete**: user-visible text, spoken audio, asset filenames, on-device paths, env vars (`ISORA_*`), storage keys and the KiCad project all read I-Sora. **`BRANDING.md` is the source of truth** for the handful of things that deliberately still say "AuralAI" — read it before renaming anything that matches `/aural/i`.

The three that bite most often:
- **Protocol constants** `auralai-e2e-salt` / `auralai-e2e-v1` / `auralai-pair:` (`web/lib/e2e.ts` ↔ `device/utils/crypto_box.py`) — shared wire format with deployed AuralAI devices. **Never rebrand.**
- **`"auralai"` as a white-label brand value** — upstream's hidden ISORA ⇄ AuralAI toggle (long-press the `/buttons` logo). I-Sora only changes the *default* to `"isora"`.
- **The English word "aural"** — `_start_aural_engine()`, "the aural pipeline", "binaural". Means *hearing*, not the brand.

**Written "I-Sora", spoken "Isora".** `AudioManager._find_wav` maps `-` → `_`, so a spoken "I-Sora siap digunakan." would look for `i_sora_siap_digunakan.wav` and miss the real file — and gTTS reads the hyphen aloud. Keep every `SYSTEM_EVENTS` key equal to the `_find_wav` safe-name of its spoken text.

## Repos & syncing with upstream (read before "update X from aural")

- `origin` = `github.com/kutilz/isora` (this repo)
- `upstream` = `github.com/kutilz/AuralAI-SDK` (branch `master`, the shared software)

When the user says *"there's an update in aural"* / *"sync &lt;X&gt; from AuralAI-SDK"*: bring the change into the shared files, then re-apply the brand (see `BRANDING.md`). `isora` was imported with a *fresh* history (no shared commits), so a blind `git merge upstream/master` conflicts widely — sync per-file (`git fetch upstream`; `git checkout upstream/master -- <path>`). Note the user's local `AuralAI-SDK` working tree is often **ahead of `origin/master`**; when they point at the directory, copy from the directory, not from `upstream/master`.

## Architecture (five cooperating parts)

1. **`device/`** — MaixCAM firmware (MaixPy/Python). Camera → YOLO inference → audio cues, runs offline. Entry points: `device/main.py` (on-device dashboard) and `device/isora_maix.py` (companion-PC mode). Config in `device/config.py`. Cloud client `device/core/cloud.py`. Device UI source is `device/server/src/` (Preact+Vite) whose **build output is committed** to `device/server/static/app/` (the device has no Node). `device/server/static/buttons.html` is the blind-user button console served at `/`. `device/system/` holds what runs OUTSIDE the app tree and is installed to `/etc` by `tools/run.py --autostart`: the WiFi roam hook (`wifi_roam.sh` + `wifi_prefer.sh` + `S31wifiroam` — udhcpc never renews on its own when wpa_supplicant changes network), `release.py` (release switch + rollback) and `supervise.sh` (the app supervisor `S26isoraapp` starts: respawns a crashed app, SIGKILLs one whose `/tmp/isora_alive` heartbeat from `utils/liveness.py` goes stale, one reboot at most until a healthy run; exit 0/130/143 = deliberate stop, never respawned). Edit them there, never on a unit; `.gitattributes` keeps them LF.
2. **`companion/`** — PC-side Flask server (OpenAI Vision, MJPEG, browser TTS) for the tested MVP / dev without a fully self-contained device.
3. **`web/`** — Next.js (App Router) cloud hub. **This is the only piece deployed to Vercel.** Two route groups: `app/(marketing)` is the public site (landing, `/docs`, `/preview`) with the top nav; `app/(shell)` is the **installable PWA** — a phone-Settings-style app at `/app` (device list → `/app/[id]` settings → `/app/tambah` pairing) plus the **camera simulator** at `/simulasi`. Backed by Supabase; Indonesian-first copy in `web/lib/i18n.ts`. `/pair` and `/dashboard` are redirects to the new routes.
4. **`hardware/`** — PCB + enclosure. KiCad project `hardware/electronics/isora-glasses/` (7-page schematic, SG2002 QFN88) with generated libraries `Isora`, `Isora_Power`, `Isora_Periph` in `hardware/electronics/lib/`. The schematic is **generated code**: edit `hardware/scripts/gen_sch.py`, not the `.kicad_sch` files.
5. **`android/`** — **I-Sora Dengar**, a small native Android app (Kotlin, platform APIs only — no AndroidX, no libraries). It does what `/dengar` does, plus what a web page cannot: pair Bluetooth earphones from inside the app (`Earphones.kt`; Android still shows its own one-tap "Pair?" dialog, and only the system may switch an already-paired earphone — they reconnect themselves when switched on), and keep playing with the screen off (`ListenService`, a media-playback foreground service). It finds the glasses by sweeping the phone's own WiFi/hotspot /24 for `GET /status` (`DeviceFinder.kt`) — mDNS does not see the phone's own hotspot, and a blind user cannot type an IP. Speaks the same `/listen/*` protocol as `listen.html`, so the device needs no change for it. Between clips `ClipPlayer` keeps its track running on silence: a stopped `AudioTrack` does not restart until its buffer is full, which stalled a 156 ms chime for ±2 s, and the running track is also meant to keep Bluetooth awake. Clips up to 6 s are cached on the phone by text + length (`ClipCache`), because the glasses' web server can take over a second to serve one while loading a model. No iOS version: iOS has no API for an app to pair earphones.

**Cloud relay:** the device registers and long-polls the web hub; the browser pushes config + API keys that are **E2E-encrypted** to the device's public key. The crypto and QR-token formats are a shared contract (see the protocol constants above).

**Pairing leads with the ACTION button** (`/app/tambah`): the phone opens a session (`/api/pair/session`) and waits, the person presses the button on the device they are holding, and the device claims itself via `/api/pair/confirm`. That press binds to a waiting session by `net_hash` first and, failing that, to the only session waiting anywhere — refusing when more than one is, since two strangers pressing inside the same 3-minute window cannot be told apart. It needs no typing and no sight, which is the point. Behind it, fewest-steps first: *auto* (`/api/pair/nearby` — the device and the phone reach the relay from the same public IP, so the hub can list unclaimed devices "here"; offered only when there's **exactly one** candidate, because CGNAT can share an IPv4 between households), *camera-QR*, then the *spoken code* — which is still minted and still valid but **no longer spoken**, so it is effectively a last resort for a device whose button is broken (`utils/identity.pairing_button_phrase` replaced `pairing_phrase` as the prompt). The same signal (`devices.net_hash`, a keyed hash — never a raw IP, see `web/lib/net.ts`) drives the `same_network` flag that decides whether the app shows a device's LAN control link. A browser on HTTPS **cannot** fetch a plain-HTTP `.local` address at all, so this indirection is the only local discovery a web app can do.

**Pairing is not the end of the flow, and no step may dead-end.** The claim completes on the DEVICE the moment the button is pressed, so the phone can be closed one second later and the relay would remember nothing about the settings still owed. The device therefore reports `setup_completed` and `ai_ready` in its heartbeat (`core/cloud.py`), `web/lib/devices.ts:needsSetup` reads them, and an unfinished device is offered again on `/app` (amber dot), at the top of `/app/tambah` (`LinkedDevices`, which is also the way out when someone returns to a pairing screen the device will now refuse), and by `/app/[id]` treating `?baru=1` as a hint rather than the source of truth. Saving first setup hands over to `WelcomeOverlay`, which polls `GET /api/devices/[id]/config?command_id=` (`useCommandAck` — the ACK deletes the row, so "gone" means applied) and then moves to the device screen by itself; every screen that waits also carries a way forward that works immediately.

**There is no sign-up.** Opening `/app` mints an *anonymous* Supabase user (`web/lib/supabase/session.ts` → `ensureSession()`), so `devices.owner_user_id`, every RLS policy and every route handler are unchanged — only the way an identity is obtained. This needs **"Allow anonymous sign-ins"** enabled in Supabase → Authentication → Sign In / Providers. `/login` is now optional and does one of two things: with an anonymous session it calls `updateUser({ email })` to attach an email to *that same user id* (so paired devices survive), otherwise it sends a plain magic link so a second phone can reach devices paired on the first. `/auth/callback` therefore handles **both** `?code=` (PKCE) and `?token_hash=&type=` (the `email_change` confirmation). A 401 anywhere in the app means a stale cookie, not "please log in" — the clients silently re-mint instead of showing a sign-in wall.

**The simulator (`web/lib/sim/`) is a port of device logic, not a lookalike.** `vision.ts` ← `utils/logger.position_from_bbox` + `utils/distance.band`; `announce.ts` ← `utils/announce_policy.decide`; `constants.ts` ← `config.NAV_OBJECTS` + the thresholds + `audio_manager`'s phrase maps. `money.ts` ← `utils/money` + the `money_*` config values. It swaps YOLO11n for COCO-SSD (TensorFlow.js), runs the device's own banknote YOLO26n through ONNX Runtime Web (`money-detector.ts`, self-hosted in `public/models/`), and swaps pre-rendered WAVs for WebAudio + Web Speech. **Retune the device → retune `lib/sim/` in the same change**, or the simulation quietly starts lying.

**Online navigation (`modes/scan_narrator.py`):** short ACTION in explorer toggles it (spoken "navigasi daring aktif / mati"; off on every mode change). YOLO keeps running for hazards; every `scan_interval_s` (3–60, settable from `/buttons` and the cloud app) a photo goes to the cloud with `SCENE_PROMPT_SCAN`. Only the JPEG encode runs on the AI loop thread — the HTTP call *and* `speak_scene` run on a worker, because the word-cache concat alone blocked the loop 0.7 s on the device. The next photo waits for `AudioManager.is_quiet()`, stale answers (> `scan_stale_s`) are dropped, and `speak_scene(still_wanted=...)` keeps a switch-off from being overtaken by a sentence still rendering.

**Scan bayar (`modes/pay_mode.py`, mode key `qris`):** each tick spends its frame on either the banknote model or MaixPy's QR finder, alternating; a note is said once when it arrives (`utils/money.PresenceTracker`, offline WAV per denomination), a QRIS code is read out with merchant + nominal, ACTION still does the AI-checked scan. The NPU holds one model at a time — `Orchestrator._MODE_MODELS` swaps the nav YOLO (explorer) for `money_model_path` (scan bayar). The banknote model is YOLO26n read by MaixPy's **YOLOv8** decoder (cut at the raw head; reg_max=1 makes that equivalent) and is not shipped by `tools/deploy.py` — see `tools/money_model/README.md`.

**Listening on the phone (`/dengar`, `core/phone_audio.py`):** the glasses have no usable Bluetooth (SMD rework), so the phone plays the audio and routes it to its own Bluetooth earphones/speaker. The phone opens `http://<device-ip>:8080/dengar` — plain HTTP on the LAN, not the cloud app, because an HTTPS page cannot fetch the device. Every clip `AudioManager._play_pcm_bytes` plays is offered to the phone over a long-poll; while the phone polls it may silence the device speaker. Fail-safe: a phone that stops polling expires after 5 s and the speaker takes over again.

**Mode PIMNAS (`/pimnas`, `cfg.event_mode`):** an event profile for a live demo on a venue network nobody can trust, steered by a second person on the phone that is also the device's hotspot (LAN plain HTTP, like `/dengar`; the cloud app is no use here). While on: `updater` neither fetches nor switches; `AI_TIMEOUT_S` drops to `event_ai_timeout_s`; context mode keeps the nav YOLO loaded (`model_for_mode`) so a failed describe is followed by `AIEngine._offline_fallback` reading out real detections from the pre-recorded nav phrases; collection/benchmark/stress POSTs answer 423. **Speech presets** (`utils/speech_presets.py`): a sentence typed on the page is rendered ONCE (cloud voice, else a full word-cache hit) and stored as PCM in `speech_presets_dir` — outside the pruned `tts_cache_dir` — so its button plays with no network. The page's camera preview is opt-in: a watched `/snapshot` makes context mode read frames every tick, which is the load that starves the WiFi.

**Auto-update (`core/updater.py` + `device/system/release.py`):** once a day a unit reads `github.com/kutilz/isora/releases/latest/download/isora-device.json`, checks its ECDSA P-256 signature against `RELEASE_PUBKEY_B64` (pure-Python verify in `utils/release_sig.py`), downloads + hashes the tarball, stages it in `/root/isora-releases/<v>/` and writes `pending`. The switch happens in the init script (`/etc/isora/release.py boot`) at the next start — at boot, or after 10 quiet minutes in idle mode — and the new release runs on **trial** until `confirm_when_healthy()` vouches for it; unconfirmed after 240 s or 3 starts → rolled back and marked bad. Every step is a rename, so a power cut at any point leaves a startable app. `/root/isora` becomes a symlink. Inert until `--autostart` installed the helper. The **private signing key is NOT in the repo**: `~/.isora/release-signing-key.json` on the release laptop. Deploys via `tools/deploy.py`/`run.py` stamp `VERSION` as `<latest device-v tag>+dev.<time>`, so a dev unit is only replaced by a strictly newer release.

**Audio pipeline (has a caching gotcha):** `tools/generate_audio.py` uses gTTS, which writes **MP3 bytes into `.wav` files**. On the device, `device/core/audio_manager.py` converts each `.wav` → `.pcm` (`s16le`, 48 kHz, mono) via ffmpeg and **caches the `.pcm`**, which is what actually plays. So to change a spoken line you must replace **both** the `.wav` and the `.pcm` (or delete the `.pcm` so it regenerates). Chimes are real RIFF WAV synthesized offline with numpy. A `.pcm` is valid only while it is non-empty and carries its WAV's mtime (`_pcm_is_fresh`); `tools/deploy.py` preserves mtimes so a deploy does not invalidate the cache, and the app re-converts anything stale in the background after boot. To see why something was or wasn't spoken, read `GET /audio/trace` on the unit (every clip queued → played / cut-and-replayed / dropped with a reason). Opening or closing the camera must hold `audio_manager._codec()` — MaixPy's multimedia init drops whatever the speaker is playing.

**Field diagnostics (`utils/diag.py`):** `[diag] <kind> key=value` lines in the normal log, readable from `GET /logs` even when the SD card has gone read-only. `ai_call` splits a slow answer into the model's own time (`server_s`) and everything else (`net_s`); `net_probe` records the link and CPU while a call is still slow; `root_ro` marks the root filesystem going read-only, which silences any sentence missing from the word cache. `press` / `press_merged` / `press_run` show every ACTION press, those overwritten in the single pending-command slot, and how long a press waited before its photo was taken. `debug_save_frames` keeps the photo behind each describe in `/root/captures/debug`; it can show people, so it is off by default.

## Commands

**Web app (the Vercel deploy):**
```bash
cd web
npm install
npm run dev            # http://localhost:3000
npm run build          # production build (must pass before deploy)
npm run lint
```
```bash
node scripts/gen-icons.mjs   # regenerate public/icons/* from the beacon mark (sharp)
```
Deploy: Vercel project `isora`, **Root Directory = `web`**, prod domain `isora-smartglasses.vercel.app`. Env vars: `NEXT_PUBLIC_SITE_URL`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, optional `PAIR_SIGNING_SECRET` (see `web/.env.example`). Provision Supabase with `web/supabase/schema.sql`, then in Authentication → Sign In / Providers enable **anonymous sign-ins** (required — the app has no sign-up) and **email magic links** (optional, for the backup/second-phone path). The script is idempotent, so **re-run it after pulling** (it adds `devices.net_hash`, an index, and column-level grants).

`getUserMedia` needs a secure context: `/simulasi` works on `localhost` and on Vercel, but not over plain HTTP from a LAN IP.

**Device UI (rebuild after editing `device/server/src/`):**
```bash
cd device/server/src
npm install
npm run build          # emits to ../static/app/ — commit the output alongside source
```

**Device tests:**
```bash
python -m pytest device/tests -q     # ~600 tests, no hardware needed
# test_release_state.py (+1 updater test) need symlinks → skipped on Windows; run them in WSL:
#   wsl python3 -m pytest device/tests/test_release_state.py device/tests/test_updater.py
```

**PC-side tooling (Python):**
```bash
pip install -r requirements_pc.txt
python tools/generate_audio.py --from-wordlist   # regenerate speech (gTTS, lang id); also --chimes / --legacy / --dry-run
python tools/deploy.py --host <maixcam-ip>        # SCP device/ + audio/ to /root/isora + /root/audio (paramiko); --audio-only, --dry-run
python tools/run.py --autostart                   # install the boot chime + app init scripts + device/system/* (WiFi hook, release helper)
python tools/release.py build && python tools/release.py publish   # signed device release (commit first; units take it within a day)
python tools/mock_device.py --base-url http://localhost:3000   # exercise the cloud relay without hardware
python companion/webserver.py                     # PC companion (needs OPENAI_API_KEY in companion/.env)
python companion/run_desktop.py                   # simulate the device with a webcam
```
Device host/user/pass for deploy come from `--host`/`--user`/`--password` flags or `ISORA_MAIX_HOST`/`_USER`/`_PASS` env (default user/pass `root`/`root`).

**Android app (`android/`, build on the PC — it has Android Studio's JBR + SDK):**
```bash
cd android
./gradlew assembleDebug testDebugUnitTest lintDebug   # JAVA_HOME = Android Studio's jbr; local.properties sdk.dir
# → app/build/outputs/apk/debug/app-debug.apk (sideload; no release keystore yet)
```

**Hardware (KiCad, all generated + self-verifying):**
```bash
python hardware/scripts/gen_sch.py            # regenerate all 7 schematic pages
python hardware/scripts/verify_sg2002_libs.py # library regression checks
python hardware/scripts/verify_sch.py         # 139 netlist checks vs Sophgo HW guide + datasheets
bash   hardware/scripts/fetch-sophgo-ref.sh   # re-fetch the 77 MB vendor reference
```

## Conventions / gotchas

- `tools/_*.py` are **one-off scratch scripts** (deploy/probe/diagnose experiments), not supported tooling. They hardcode absolute paths into this repo.
- `hardware/reference/sophgo/` (77 MB of official Sophgo docs) is **gitignored** and re-fetchable via `fetch-sophgo-ref.sh`. The grep-able text extraction in `hardware/reference/_text/` **is** committed.
- Web theme tokens (indigo `#2C3680` + amber `#F4A23B`, Plus Jakarta Sans + JetBrains Mono) live in `web/app/globals.css`; the beacon logo is `web/components/Logo.tsx`. Amber is low-contrast on white — keep it for the logo/badges/dark blocks, not body text/links.
- The root `README.md` is the AuralAI-era SDK doc (dev-facing, still references the upstream repo by name on purpose); `web/README.md` and `hardware/README.md` are I-Sora docs.
- gitignored: `node_modules/`, `web/.next/`, `web/.vercel/`, `*.env*.local`, `models/`, `audio/*.wav`, `__pycache__/`, `hardware/reference/sophgo/`. Note `audio/*.wav` means regenerated speech is **not** committed — only `audio/Isora_Audio_Wordlist.md` is.

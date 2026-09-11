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

## Architecture (four cooperating parts)

1. **`device/`** — MaixCAM firmware (MaixPy/Python). Camera → YOLO inference → audio cues, runs offline. Entry points: `device/main.py` (on-device dashboard) and `device/isora_maix.py` (companion-PC mode). Config in `device/config.py`. Cloud client `device/core/cloud.py`. Device UI source is `device/server/src/` (Preact+Vite) whose **build output is committed** to `device/server/static/app/` (the device has no Node). `device/server/static/buttons.html` is the blind-user button console served at `/`.
2. **`companion/`** — PC-side Flask server (OpenAI Vision, MJPEG, browser TTS) for the tested MVP / dev without a fully self-contained device.
3. **`web/`** — Next.js (App Router) cloud hub. **This is the only piece deployed to Vercel.** Public landing/docs/audio-preview + pairing (spoken code or camera-QR) + device dashboard, backed by Supabase. Indonesian-first copy in `web/lib/i18n.ts`.
4. **`hardware/`** — PCB + enclosure. KiCad project `hardware/electronics/isora-glasses/` (7-page schematic, SG2002 QFN88) with generated libraries `Isora`, `Isora_Power`, `Isora_Periph` in `hardware/electronics/lib/`. The schematic is **generated code**: edit `hardware/scripts/gen_sch.py`, not the `.kicad_sch` files.

**Cloud relay:** the device registers and long-polls the web hub; the browser pushes config + API keys that are **E2E-encrypted** to the device's public key. The crypto and QR-token formats are a shared contract (see the protocol constants above).

**Audio pipeline (has a caching gotcha):** `tools/generate_audio.py` uses gTTS, which writes **MP3 bytes into `.wav` files**. On the device, `device/core/audio_manager.py` converts each `.wav` → `.pcm` (`s16le`, 48 kHz, mono) via ffmpeg and **caches the `.pcm`**, which is what actually plays. So to change a spoken line you must replace **both** the `.wav` and the `.pcm` (or delete the `.pcm` so it regenerates). Chimes are real RIFF WAV synthesized offline with numpy.

## Commands

**Web app (the Vercel deploy):**
```bash
cd web
npm install
npm run dev            # http://localhost:3000
npm run build          # production build (must pass before deploy)
npm run lint
```
Deploy: Vercel project `isora`, **Root Directory = `web`**, prod domain `isora-smartglasses.vercel.app`. Env vars: `NEXT_PUBLIC_SITE_URL`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` (see `web/.env.example`). Provision Supabase with `web/supabase/schema.sql` + email magic-link auth.

**Device UI (rebuild after editing `device/server/src/`):**
```bash
cd device/server/src
npm install
npm run build          # emits to ../static/app/ — commit the output alongside source
```

**Device tests:**
```bash
python -m pytest device/tests -q     # 463 tests, no hardware needed
```

**PC-side tooling (Python):**
```bash
pip install -r requirements_pc.txt
python tools/generate_audio.py --from-wordlist   # regenerate speech (gTTS, lang id); also --chimes / --legacy / --dry-run
python tools/deploy.py --host <maixcam-ip>        # SCP device/ + audio/ to /root/isora + /root/audio (paramiko); --audio-only, --dry-run
python tools/run.py --autostart                   # install the boot chime + app init scripts
python tools/mock_device.py --base-url http://localhost:3000   # exercise the cloud relay without hardware
python companion/webserver.py                     # PC companion (needs OPENAI_API_KEY in companion/.env)
python companion/run_desktop.py                   # simulate the device with a webcam
```
Device host/user/pass for deploy come from `--host`/`--user`/`--password` flags or `ISORA_MAIX_HOST`/`_USER`/`_PASS` env (default user/pass `root`/`root`).

**Hardware (KiCad, all generated + self-verifying):**
```bash
python hardware/scripts/gen_sch.py            # regenerate all 7 schematic pages
python hardware/scripts/verify_sg2002_libs.py # library regression checks
python hardware/scripts/verify_sch.py         # 134 netlist checks vs Sophgo HW guide
bash   hardware/scripts/fetch-sophgo-ref.sh   # re-fetch the 77 MB vendor reference
```

## Conventions / gotchas

- `tools/_*.py` are **one-off scratch scripts** (deploy/probe/diagnose experiments), not supported tooling. They hardcode absolute paths into this repo.
- `hardware/reference/sophgo/` (77 MB of official Sophgo docs) is **gitignored** and re-fetchable via `fetch-sophgo-ref.sh`. The grep-able text extraction in `hardware/reference/_text/` **is** committed.
- Web theme tokens (indigo `#2C3680` + amber `#F4A23B`, Plus Jakarta Sans + JetBrains Mono) live in `web/app/globals.css`; the beacon logo is `web/components/Logo.tsx`. Amber is low-contrast on white — keep it for the logo/badges/dark blocks, not body text/links.
- The root `README.md` is the AuralAI-era SDK doc (dev-facing, still references the upstream repo by name on purpose); `web/README.md` and `hardware/README.md` are I-Sora docs.
- gitignored: `node_modules/`, `web/.next/`, `web/.vercel/`, `*.env*.local`, `models/`, `audio/*.wav`, `__pycache__/`, `hardware/reference/sophgo/`. Note `audio/*.wav` means regenerated speech is **not** committed — only `audio/Isora_Audio_Wordlist.md` is.

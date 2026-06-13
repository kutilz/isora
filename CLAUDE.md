# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**I-Sora** ("Melihat dengan Suara") — assistive smart glasses for blind/low-vision users in Indonesia. A **Sipeed MaixCAM** device recognizes surroundings (YOLO object detection, scene description, QRIS) and speaks them in Indonesian.

I-Sora is a **rebrand of AuralAI** — *the same software*, different branding and hardware. Internal "AuralAI" references (code, env vars like `AURAL_*`, `auralai_*` filenames, protocol constants) are **intentional and fine** — only **user-visible** text/audio/docs/UI must read **I-Sora**. Do not do a sweeping internal rename.

## Repos & syncing with upstream (read before "update X from aural")

- `origin` = `github.com/kutilz/isora` (this repo, the I-Sora fork)
- `upstream` = `github.com/kutilz/AuralAI-SDK` (branch `master`, the shared software)

When the user says *"there's an update in aural"* / *"sync &lt;X&gt; from AuralAI-SDK"*: the shared software lives upstream; this repo adds a **branding overlay**. Apply the upstream change to the **shared files** while preserving the overlay. **`BRANDING.md` is the source of truth** — it lists every overlay file and the exact sync workflow. Note: `isora` was imported with a *fresh* history (no shared commits), so a blind `git merge upstream/master` conflicts widely — sync per-file (`git fetch upstream`; `git checkout upstream/master -- <path>` for shared paths; reconcile overlay paths by hand).

## Architecture (three cooperating parts)

1. **`device/`** — MaixCAM firmware (MaixPy/Python). Camera → YOLO inference → audio cues, runs offline. Entry points: `device/main.py` (on-device dashboard) and `device/aural_maix.py` (companion-PC mode). Config in `device/config.py`. Cloud client `device/core/cloud.py`. Device UI source is `device/server/src/` (Preact+Vite) whose **build output is committed** to `device/server/static/app/` (the device has no Node).
2. **`companion/`** — PC-side Flask server (OpenAI Vision, MJPEG, browser TTS) for the tested MVP / dev without a fully self-contained device.
3. **`web/`** — Next.js (App Router) cloud hub. **This is the only piece deployed to Vercel.** Public landing/docs/audio-preview + pairing (spoken code or camera-QR) + device dashboard, backed by Supabase. Indonesian-first copy in `web/lib/i18n.ts`.

**Cloud relay:** the device registers and long-polls the web hub; the browser pushes config + API keys that are **E2E-encrypted** to the device's public key. The crypto and QR-token formats are a shared contract: `web/lib/e2e.ts` ↔ `device/utils/crypto_box.py`, and the `auralai-e2e-salt` / `auralai-pair:` constants **must stay identical across aural & isora** (device interop) — never rebrand them.

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

**PC-side tooling (Python):**
```bash
pip install -r requirements_pc.txt
python tools/generate_audio.py --from-wordlist   # regenerate speech (gTTS, lang id); also --chimes / --legacy / --dry-run
python tools/deploy.py --host <maixcam-ip>        # SCP device/ + audio/ to /root/aural-ai + /root/audio (paramiko); --audio-only, --dry-run
python tools/mock_device.py --base-url http://localhost:3000   # exercise the cloud relay without hardware
python companion/webserver.py                     # PC companion (needs OPENAI_API_KEY in companion/.env)
python companion/run_desktop.py                   # simulate the device with a webcam
```
Device host/user/pass for deploy come from `--host`/`--user`/`--password` flags or `AURAL_MAIX_HOST`/`_USER`/`_PASS` env (default user/pass `root`/`root`).

## Conventions / gotchas

- **Branding overlay** = the files listed in `BRANDING.md`; don't clobber them when syncing from upstream. To shrink the overlay long-term, route page titles through the existing `t.app` constant in `web/lib/i18n.ts`.
- Web theme tokens (indigo `#2C3680` + amber `#F4A23B`, Plus Jakarta Sans + JetBrains Mono) live in `web/app/globals.css`; the beacon logo is `web/components/Logo.tsx`. Amber is low-contrast on white — keep it for the logo/badges/dark blocks, not body text/links.
- The root `README.md` is the AuralAI-era SDK doc (dev-facing); `web/README.md` is rebranded.
- gitignored: `node_modules/`, `web/.next/`, `web/.vercel/`, `*.env*.local`, `models/`, `audio/*.wav`, `__pycache__/`.

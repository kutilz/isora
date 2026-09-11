# I-Sora branding overlay & upstream sync

I-Sora and **AuralAI** are the *same software*, different branding + hardware.
Shared software lives upstream at **github.com/kutilz/AuralAI-SDK** (`master`).
This repo (`kutilz/isora`) is the **I-Sora fork**: identical code + a small
**branding overlay**. When software changes upstream, sync it here while keeping
the overlay files below intact.

> Note: `isora` was imported as a fresh history (no shared commits with upstream),
> so a plain `git merge upstream/master` conflicts widely. Sync per-file instead
> (copy changed shared files; never clobber the overlay). The `upstream` remote is
> configured: `git fetch upstream` then diff/copy the paths you need.

## Branding overlay — DO NOT overwrite from upstream
These files differ from AuralAI on purpose. After pulling upstream changes, re-check them.

**Web (`web/`)**
- `lib/i18n.ts` — app name (`I-Sora`), tagline ("Melihat dengan Suara"), all copy
- `app/layout.tsx` — `<title>`/description + Plus Jakarta Sans / JetBrains Mono fonts
- `app/globals.css` — `:root` theme tokens (indigo `#2C3680` + amber `#F4A23B`)
- `components/Logo.tsx` — beacon mark (I-Sora-only file)
- `components/Nav.tsx`, `components/Footer.tsx` — wordmark + logo
- `app/docs/page.tsx`, `app/docs/[slug]/page.tsx`, `app/pair/page.tsx`,
  `app/dashboard/page.tsx`, `app/preview/page.tsx`, `app/login/page.tsx`,
  `app/pair/PairClient.tsx` — page titles / brand strings
- `components/QrSetup.tsx`, `components/DeviceConfigForm.tsx` — example URL/placeholder
- `content/docs/*.md` — "I-Sora" in the guides
- `public/audio/isora_siap_digunakan.wav` — greeting renamed + re-recorded ("Isora …")
- `package.json` (name `isora-web`), `.env.example`, `README.md`, `supabase/schema.sql` (header)

**Device UI (`device/server/`)** — rebuild `src/` → `static/app/` after editing
- `src/i18n/{id,en}.json` — `common.app_name`, `guide.hero_title`
- `src/{admin,companion,guide,setup}.html` — `<title>` / OG meta
- `src/pages/{admin,companion,setup}.tsx` — header wordmark, footer, spoken-line quotes
- `src/components/companion/{StatusBanner,LiveView,ActivityFeed}.tsx` — wordmark, alt text,
  CSV export name (`isora-history-*.csv`)
- `src/components/guide/{Hero,HardwareSection,AudioSection}.tsx` — alt/aria text, the
  `I-SORA` label silk-screened on the SVG module, chime table
- `static/{index,collect}.html`, `static/dashboard.js` — dev-dashboard titles + wordmarks
- `static/buttons.html` — `<title>`, header/footer wordmarks (the `aural_*` localStorage
  keys in it stay AuralAI on purpose)

**Device firmware (`device/`)**
- `config.py` — `cloud_base_url` points at the **I-Sora** hub
  (`https://isora-smartglasses.vercel.app`), not AuralAI's
- `utils/identity.py` — spoken `pairing_phrase()` / `onboarding_phrase()` say "Isora",
  default hub URL + spoken-host fallback
- `core/onboarding.py` — boot cue speaks "Isora siap digunakan.", pinned to the existing
  `auralai_siap_digunakan.wav` via `wav_name=` so already-deployed devices keep playing
  the pre-recorded file instead of falling back to gTTS
- `core/audio_manager.py` — docstring quoting the boot cue ("Isora menyala")
- `requirements_device.txt` — comment quoting the "Isora siap" cue
- `server/web_server.py` — 404 page `<title>`

**Companion (`companion/`)**
- `webserver.py` — browser UI `<title>`, `I-SORA` wordmarks, "Mulai I-Sora" button,
  spoken `rawSpeak("Sistem Isora aktif.")`
- `run_desktop.py` — `I-SORA` overlay drawn on the video feed

**Audio (`tools/generate_audio.py`)**
- `SYSTEM_EVENTS["isora_siap_digunakan"] = "Isora siap digunakan."` — the key **is** the
  generated filename and must stay the `AudioManager._find_wav` safe-name of the spoken
  text, so rename key and text together.

**Docs (`docs/`)**
- `setup.md`, `hardware_assembly.md`, `operator_runbook.md` — product name, spoken-cue
  quotes, repo URL (`github.com/kutilz/isora`), default hub URL

**On the MaixCAM (not in repo):** `/root/audio/auralai_menyala.{wav,pcm}` and
`auralai_siap_digunakan.{wav,pcm}` re-recorded to say "Isora …" (originals kept as
`*.aural.bak`). Filenames unchanged because `device/main.py` + `core/audio_manager.py`
resolve them by name.

## Pull a software update from upstream
```bash
git fetch upstream
git diff --stat HEAD upstream/master            # see what changed upstream
git checkout upstream/master -- <changed shared path>   # bring in a shared file
# review; if the path is in the overlay above, reconcile by hand instead
git commit -m "Sync <feature> from AuralAI-SDK upstream"
```
Or just ask Claude Code: *"sync &lt;change&gt; from AuralAI-SDK into isora"* — it applies
the change to the shared files and preserves this overlay.

## What stays "AuralAI" on purpose
The user-visible rebrand is complete. Everything below is **internal** and must NOT be
renamed — several of these are load-bearing:

- **Protocol constants** — `auralai-e2e-salt`, `auralai-e2e-v1`, `auralai-pair:`
  (`web/lib/e2e.ts` ↔ `device/utils/crypto_box.py`). Shared so I-Sora and AuralAI
  devices stay interoperable.
- **On-disk / on-device names** — `/root/aural-ai/`, `aural_*.log`, `systemctl aural-ai`,
  `auralai_menyala.wav`, `auralai_siap_digunakan.wav`, `audio/AuralAI_Audio_Wordlist.md`.
- **Hostnames** — `default_device_name()` → `aural-<id>`, so `aural-xxxx.local` in the
  setup wizard is accurate, not a leftover.
- **Storage keys** — `aural_token`, `auralai.lang`, `auralai.a11y.*`,
  `auralai_stress_history`. Renaming logs users out / drops their preferences.
- **Env vars** — `AURAL_MAIX_HOST`, `AURAL_COMPANION_*`, `AURAL_*_API_KEY`, …
- **Code identifiers, module docstrings, log lines, console banners** — `AuralAIHandler`,
  `auralai-ui`, `logger.info("AuralAI SDK — Starting up")`, `print("[AuralAI] …")`.
- **`README.md`** (root) and **`docs/boot-optimization.md`** — AuralAI-era engineering
  docs, dev-facing on purpose.

## Recommendation to shrink this overlay
Most overlay entries are one-off string swaps. Route page titles/metadata through the
existing `t.app` constant (in `lib/i18n.ts`) so branding collapses to ~3 files
(`i18n.ts` + `globals.css` + `Logo.tsx`) and upstream syncs become near-conflict-free.

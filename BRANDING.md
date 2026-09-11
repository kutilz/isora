# I-Sora branding & upstream sync

I-Sora and **AuralAI** are the *same software*. The shared code lives upstream at
**github.com/kutilz/AuralAI-SDK** (`master`); this repo (`kutilz/isora`) is the
**I-Sora product repo** — the same software plus the I-Sora brand, and now the
**hardware** (`hardware/`) as well.

> `isora` was imported as a fresh history (no shared commits with upstream), so a
> plain `git merge upstream/master` conflicts widely. Sync per-file instead.
> The `upstream` remote is configured: `git fetch upstream`, then diff/copy paths.

## The rebrand is complete (not an overlay of string swaps any more)

Earlier revisions of this file listed a small per-file "branding overlay". That is
no longer how this repo works. **Everything a user can see, hear, or type is
I-Sora**, including asset filenames, on-device paths, env vars, storage keys and
the hardware project. The list below is therefore inverted: it records the few
things that deliberately still say "AuralAI", and why.

### Written vs spoken — the one rule that bites

| Context | Form | Why |
|---|---|---|
| Anything displayed | **I-Sora** | the brand |
| Anything **spoken** | **Isora** (one word) | `AudioManager._find_wav` maps `-` → `_`, so "I-Sora siap digunakan." would look for `i_sora_siap_digunakan.wav` and miss `isora_siap_digunakan.wav`. gTTS would also read the hyphen aloud. |

So `device/utils/identity.py`, `device/core/onboarding.py`, `tools/generate_audio.py`
(`SYSTEM_EVENTS`) and `audio/Isora_Audio_Wordlist.md` all say **"Isora …"**.
Keep it that way, and keep each `SYSTEM_EVENTS` key equal to the `_find_wav`
safe-name of its spoken text.

## What stays "AuralAI" on purpose

1. **E2E + QR protocol constants** — `auralai-e2e-salt`, `auralai-e2e-v1`,
   `auralai-pair:` in `web/lib/e2e.ts` ↔ `device/utils/crypto_box.py` and
   `web/app/api/pair/{qr,scan}/route.ts`. Shared wire format: renaming them breaks
   pairing with every already-deployed device. **Never rebrand.**
2. **The white-label brand key** — upstream ships a hidden ISORA ⇄ AuralAI toggle
   (long-press the `/buttons` logo). `"auralai"` stays one of two valid values in
   `device/config.py`, `device/core/orchestrator.py`,
   `device/server/web_server.py` and `device/server/static/buttons.html`.
   I-Sora just **defaults** to `"isora"`.
3. **The upstream repo name** — `AuralAI-SDK` in clone URLs, `CLAUDE.md`, the root
   `README.md` and the `tools/_*.py` scratch scripts. It is the real repo name.
4. **The keyring service id** — `AuralAI-SDK::secure_keys` in
   `device/utils/secure_keys.py`. Renaming it orphans API keys already stored in
   the OS keyring.
5. **The English word "aural"** — `_start_aural_engine()` /
   `_release_aural_engine()` and comments like "the aural pipeline", plus
   "binaural" in `docs/plan_nav_ux_offline_maturation.md`. These mean *hearing*,
   not the brand.

## Renames that break already-deployed devices / your shell

A device flashed before this change keeps working, but it is running the old
layout. **Redeploy once** (`python tools/run.py --autostart`, or
`python tools/deploy.py --host <ip>`) and update your own environment:

| Old | New |
|---|---|
| `AURAL_*` env (`AURAL_MAIX_HOST`, `AURAL_COMPANION_HOST`, `AURAL_API_KEY`, …) | `ISORA_*` |
| `/root/aural-ai/` | `/root/isora/` |
| `/etc/init.d/S00aauralchime`, `S26auralapp` | `S00aisorachime`, `S26isoraapp` |
| `/tmp/aural_*`, `/root/logs/aural_*` | `/tmp/isora_*`, `/root/logs/isora_*` |
| `auralai_menyala.{wav,pcm}`, `auralai_siap_digunakan.{wav,pcm}` | `isora_menyala.*`, `isora_siap_digunakan.*` |
| `audio/AuralAI_Audio_Wordlist.md` | `audio/Isora_Audio_Wordlist.md` |
| `device/aural_maix.py` | `device/isora_maix.py` |
| storage keys `aural_token`, `auralai.lang`, `auralai.a11y.*`, `auralai_stress_history` | `isora_token`, `isora.lang`, `isora.a11y.*`, `isora_stress_history` |
| mDNS host `aural-<id>.local` | `isora-<id>.local` |
| npm packages `auralai-ui`, `auralai-web` | `isora-ui`, `isora-web` |
| hub default `https://aural-ai-six.vercel.app` | `https://isora-smartglasses.vercel.app` |

`tools/run.py` deletes the old init-script names on every install/uninstall
(`LEGACY_INIT_PATHS`), so one redeploy clears the double-chime risk. The old
`/root/aural-ai/` directory is **not** deleted automatically — remove it by hand
(`rm -rf /root/aural-ai`) once the new layout boots, and note that the old
`/root/audio/auralai_*.{wav,pcm}` greetings linger there harmlessly too.

Storage-key renames log you out of the web hub and reset UI preferences once.

## I-Sora-only files (no upstream counterpart)

- `web/components/Logo.tsx` — the beacon mark
- `web/app/globals.css` — indigo `#2C3680` + amber `#F4A23B` tokens, Plus Jakarta
  Sans / JetBrains Mono. Amber is low-contrast on white: logo/badges/focus ring
  and dark blocks only, never body text or links.
- `brand/` — brand identity explorations
- `hardware/` — PCB + enclosure (KiCad project `isora-glasses`, libraries
  `Isora`, `Isora_Power`, `Isora_Periph`)
- `BRANDING.md`, `CLAUDE.md`, `docs/PEDOMAN-PKM-KI-2026.md`

## Pull a software update from upstream

```bash
git fetch upstream
git diff --stat HEAD upstream/master          # what changed upstream
git checkout upstream/master -- <shared path> # bring in a shared file
```

Then re-apply the brand on the files you pulled: upstream says "AuralAI", this
repo says "I-Sora" (spoken: "Isora"), with the five exceptions above left alone.
Or just ask Claude Code: *"sync &lt;change&gt; from AuralAI-SDK into isora"*.

**Verify after any sync:**

```bash
python -m pytest device/tests -q                  # 463 tests
cd device/server/src && npm run build             # device UI -> ../static/app/
cd web && npm run build                           # the Vercel deploy
python hardware/scripts/verify_sg2002_libs.py     # KiCad libraries
python hardware/scripts/verify_sch.py             # 134 netlist checks
```

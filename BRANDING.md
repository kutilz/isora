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

**Device (on the MaixCAM, not in repo):** `/root/audio/auralai_menyala.{wav,pcm}` and
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

## Still TODO (deferred device-code rebrand)
The device **Python** code still says "AuralAI" in UI strings / `AURAL_*` env / hostnames.
Crypto + QR-token protocol constants (`auralai-e2e-salt`, `auralai-pair:`) are
**intentionally shared** so I-Sora and Aural devices stay interoperable — do not change them.

## Recommendation to shrink this overlay
Most overlay entries are one-off string swaps. Route page titles/metadata through the
existing `t.app` constant (in `lib/i18n.ts`) so branding collapses to ~3 files
(`i18n.ts` + `globals.css` + `Logo.tsx`) and upstream syncs become near-conflict-free.

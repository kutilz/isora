# AuralAI UI source

Preact + Vite source for `/`, `/admin`, `/guide`, `/setup`. Built output
lives in `../static/app/` (committed to the repo so the MaixCAM device,
which has no Node.js, can serve the bundle as plain static files).

## Workflow

```bash
cd device/server/src
npm install            # once
npm run build          # produces ../static/app/{companion,admin,guide,setup}.html + assets/
npm run dev            # local dev server on http://localhost:5173 (proxies /status etc to localhost:8080)
```

After `npm run build`, **commit the regenerated `device/server/static/app/`**
along with the source change. The device is dumb — it only knows static
files.

## Adding English

The whole UI is wired through `lib/i18n.ts`. Strings live in `i18n/id.json`
(Indonesian, default). To add English:

1. Translate every key in `i18n/id.json` and save as `i18n/en.json`.
2. In `components/atoms/A11yBar.tsx`, uncomment the language `<select>`
   block (it's there but disabled until `en.json` is populated).
3. `setLang("en")` from `lib/i18n.ts` is already exported; the toggle in
   step 2 just plumbs it through and persists the choice to
   `localStorage["auralai.lang"]`.

No component code needs to change — components already call `t("path.to.key")`.

## Layout

```
src/
├── companion.html  guide.html  admin.html  setup.html   ← entries
├── pages/{companion,admin,guide,setup}.tsx              ← root render
├── components/
│   ├── atoms/      Icon, AssetImage, A11yBar, SkipLink
│   ├── companion/  StatusBanner, LiveView, ModeSwitcher, …
│   ├── admin/      DevSidebar, AdminRibbon, DebugOverlay
│   ├── guide/      Hero, StoryboardSection, HardwareSection, …
│   └── setup/      StepStrip + Step1..4
├── lib/            api, polling, manifests, a11y, i18n
├── i18n/           id.json, en.json (stub)
└── styles/         global.css (imports ../static/tokens.css)
```

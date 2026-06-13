# Admin Interface — full spec

> Goal: admin / operator harus bisa **debug persis apa yang user lihat & dengar**,
> sehingga semua UI pendamping juga aksesibel di `/admin`, plus tools teknis tambahan.

## 1. Routing & access

| Path                    | Siapa                       | Auth                         |
| ----------------------- | --------------------------- | ---------------------------- |
| `/`                     | Pendamping                  | `device_token` (cookie/header) |
| `/admin`                | Operator / dev              | `device_token` + role flag   |
| `/admin/?as=companion`  | Operator melihat sebagai pendamping | sama |

Tambahkan field di `config.py` `_DEFAULTS`:

```python
"admin_role_token": "",  # bila kosong, hanya satu role (semua admin)
```

Kalau `admin_role_token` di-set, `device_token` punya akses Companion saja;
`admin_role_token` punya akses keduanya.

## 2. Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│ A11y bar (sama dengan companion)                                    │
├─────────────────────────────────────────────────────────────────────┤
│ Header — logo • [VIEW: Pendamping ▼] • nav admin • token info       │
│                                                                     │
│ Tombol "VIEW" di tengah = role-switcher.                            │
│  - Pendamping  → render companion-dashboard.jsx                     │
│  - Admin       → render companion-dashboard.jsx + Dev sidebar       │
│  - Setup       → render setup-wizard.jsx (selalu reachable)         │
│  - Logs        → render full log viewer (existing dashboard.js)     │
│  - Benchmark   → existing benchmark modal sebagai full page         │
│  - AI Settings → existing modal sebagai full page                   │
├──────────────────────────────────────┬──────────────────────────────┤
│                                      │                              │
│  COMPANION DASHBOARD (verbatim,      │  DEV SIDEBAR (collapsible)   │
│  the entire 6.1 layout)              │  - Latency mini-graph        │
│                                      │  - Live log tail (last 20)   │
│  + extra "DEBUG OVERLAY" toggle      │  - I2C probe button          │
│    di status banner: saat aktif,     │  - Restart service           │
│    semua angka teknis muncul         │  - Soft/hard reset           │
│    overlay (FPS, ms, queue depth,    │  - Open SSH instructions     │
│    confidence threshold, etc)        │                              │
│                                      │                              │
└──────────────────────────────────────┴──────────────────────────────┘
```

## 3. Wajib: semua fitur companion dapat diakses

Termasuk yang di companion biasanya one-time / hidden:

- **Setup wizard**: di companion, otomatis muncul kalau `setup_completed=false`.
  Di admin: selalu reachable dari menu "Setup". Bisa di-rerun untuk debug,
  ganti WiFi, atau ganti API key tanpa harus reset config.
- **A11y bar**: sama persis. Admin juga sering perlu tes "Kontras tinggi"
  mode untuk membantu debug screen reader.
- **Filter aktivitas**: admin punya filter tambahan "Semua sistem" (di
  companion default hide system noise).
- **Volume slider**: admin bisa juga set volume `> 100` (preview clipping)
  dan `< 0` (mute hardware) — diberi label "preview mode".

## 4. Debug overlay

Toggle di header admin: ☐ Tampilkan angka teknis (Debug Overlay)

Saat aktif, overlay tampil di atas tiap kartu Companion:

| Komponen        | Overlay info                                       |
| --------------- | -------------------------------------------------- |
| LiveView        | FPS, latency cam/inf/post, queue depth             |
| ActivityFeed    | Log level, source module, raw timestamp ms         |
| ModeSwitcher    | Last mode-change timestamp + duration             |
| VolumeControl   | Software vol vs hardware vol register              |
| QuickStatus     | Raw battery mV, RAM bytes, temp source sensor      |
| StatusBanner    | Websocket ping ms, last commit hash, build time    |

Visual: badge `var(--ink)` background, monospace 11px, posisi top-right setiap
kartu, dengan border 1px putih untuk kontras.

## 5. Dev sidebar (kanan, 320px)

Dapat ditutup. Berisi:

1. **Latency mini-graph** — sparkline 60-detik untuk cam / inference / post /
   total. Sumber: same as `latency-bar` di dashboard lama.
2. **Live log tail** — last 20 baris log device. Pakai font mono, 12px,
   auto-scroll. Tombol "Buka log penuh" → halaman `/admin/logs`.
3. **Quick actions**:
   - 🔌 Tes koneksi AI (panggil endpoint test current provider)
   - 🔋 Probe I2C battery HAT
   - ♻ Restart service (`POST /admin/restart`)
   - 🔄 Hard reboot (`POST /admin/reboot`)
   - 📊 Buka benchmark
   - ⚙ Buka AI settings
   - 📋 Copy config.json ke clipboard
4. **Build info**:
   - Commit short SHA, build date, Python ver, MaixPy ver.

## 6. Reused components (jangan duplikasi)

- Companion dashboard JSX dipakai apa adanya — admin hanya membungkus.
- Setup wizard JSX dipakai apa adanya.
- Modal benchmark dan AI settings lama di `index.html` lama → ekstrak ke
  komponen `<BenchmarkPanel>` dan `<AISettingsPanel>` yang reusable.
  Companion **tidak menampilkan** ini; admin **menampilkan** sebagai full page.

## 7. Permissions matrix

| Aksi                        | Companion | Admin |
| --------------------------- | --------- | ----- |
| Lihat camera                | ✅        | ✅    |
| Lihat caption terakhir      | ✅        | ✅    |
| Ganti mode                  | ✅        | ✅    |
| Atur volume                 | ✅        | ✅    |
| Atur audio_mode (chime/speech) | ✅     | ✅    |
| Lihat riwayat (filtered)    | ✅        | ✅    |
| Setup wizard (one-time)     | ✅        | ✅ (anytime) |
| Lapor masalah               | ✅        | ✅    |
| Panggil pengguna            | ✅        | ✅    |
| Matikan device              | ✅        | ✅    |
| Setup wizard (rerun)        | ❌        | ✅    |
| AI provider / API key       | ❌        | ✅    |
| Prompt editing              | ❌        | ✅    |
| Benchmark                   | ❌        | ✅    |
| Raw log stream              | ❌        | ✅    |
| Latency monitor             | ❌        | ✅    |
| I2C probe                   | ❌        | ✅    |
| Restart service             | ❌        | ✅    |
| Hard reboot                 | ❌        | ✅    |
| Mengirim test audio file    | ❌        | ✅    |
| Edit config.json mentah     | ❌        | ✅    |

## 8. Visual differentiation

Admin page wajib punya **ribbon merah tipis** di atas header:

```html
<div style="background:#7A1B16;color:#fff;text-align:center;
            font-size:13px;padding:4px;font-weight:600;
            letter-spacing:.08em;text-transform:uppercase;">
  ⚠ MODE ADMIN — Perubahan langsung mempengaruhi pengalaman pengguna
</div>
```

Tujuan: operator tidak lupa mereka sedang di admin saat sharing screen.

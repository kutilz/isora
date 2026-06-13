# Handoff: AuralAI Redesign — Companion Dashboard, Setup, Hardware, & User Guide

> Untuk developer (Claude Code) yang akan mengimplementasikan ulang desain di repo
> `AuralAI-SDK`. Dokumen ini mencakup pekerjaan UI/UX baru **dan** beberapa
> perubahan ringan di sisi device/server agar fitur baru bisa hidup.

---

## 1. Overview

AuralAI adalah asisten visual on-device (smart-glasses module yang menempel di
tangkai kacamata) untuk pengguna tunanetra. Repo `AuralAI-SDK` sekarang punya
satu web dashboard yang dirancang untuk **operator/dev** — penuh metrik teknis
(FPS, latency, NPU benchmark, dll).

Redesign ini memecahnya menjadi **dua interface terpisah** + **satu halaman
panduan publik**:

| Path              | Audience                                | Tujuan                                  |
| ----------------- | --------------------------------------- | --------------------------------------- |
| `/`               | **Pendamping** (guru SLB, keluarga)     | 7 tugas inti, ramah HP, WCAG 2.1 AA     |
| `/admin`          | **Operator / dev**                      | Semua kontrol — termasuk debugging      |
| `/guide`          | **Publik** (calon user, donatur, dosen) | Preview cara pakai sebelum punya device |
| `/setup` (di `/`) | Wizard satu kali untuk pendamping baru  | WiFi → API key → uji                    |

> **Catatan:** dashboard operator lama (`device/server/static/index.html`) tidak
> dihapus. Pindahkan ke `/admin` sebagai dasar, lalu **tambahkan** semua fitur
> pendamping di sana juga supaya admin bisa debug apa yang user lihat.

---

## 2. About the Design Files

Semua file di folder `designs/` adalah **referensi desain berbasis HTML/JSX** —
prototype yang menunjukkan tampilan dan perilaku yang dimaksud, **bukan** kode
produksi yang langsung dipakai. Tugasmu: **recreate desain ini di codebase target
(`AuralAI-SDK`)** mengikuti pola yang sudah ada di sana:

- Backend Python (Flask/HTTP server lama di `device/server/`,
  `companion/webserver.py`)
- Frontend: vanilla HTML/CSS/JS — tidak ada framework (lihat
  `device/server/static/index.html` + `style.css` + `dashboard.js` untuk pola)
- Komponen React di prototype harus diturunkan jadi vanilla JS modules atau
  Web Components — pilih sendiri, yang penting konsisten dengan repo.

Kalau menurutmu lebih masuk akal pakai bundler/SPA modern (Vite + React),
**tanyakan dulu ke user** sebelum tambah dependency build-system. Mungkin overkill
untuk device kecil.

---

## 3. Fidelity

**High-fidelity (hifi).** Warna, ukuran, type-scale, spacing — semua final dan
sudah dicek kontrasnya untuk WCAG 2.1 AA. Sumber tunggal: [`designs/tokens.css`](designs/tokens.css).
Jangan invent token baru — pakai yang sudah ada.

Yang **boleh kamu putuskan sendiri**:

- Struktur file/folder di codebase (selama ikut pola repo)
- Routing (Flask blueprint vs tambahan rute di `routes.py`)
- Apakah pakai htmx / Alpine / vanilla JS untuk reactivity di sisi browser

---

## 4. Yang baru di redesign ini

### 4.1 Tiga interface

1. **Companion Dashboard (`/`)** — untuk pendamping. 7 core jobs:
   - Lihat apa yang user lihat (camera + caption terakhir)
   - Cek device terhubung & status
   - Ganti mode dari jarak jauh (Jelajah / Deskripsi / QRIS)
   - Atur volume speaker
   - Setup awal (wizard 4 langkah)
   - Lihat riwayat aktivitas hari ini
   - Lapor masalah ke dev
2. **Admin Dashboard (`/admin`)** — operator/dev.
   - **Mengandung SEMUA UI pendamping di atas** (debugging: admin harus bisa
     lihat persis apa yang user lihat) PLUS:
   - Setup wizard dapat dibuka kapan saja (bukan one-time)
   - Benchmark suite, log mentah, latency monitor, AI settings, presets,
     I2C probe — semua dari dashboard lama
   - Switcher di top-bar: "Lihat sebagai: Pendamping / Admin"
3. **User Guide (`/guide`)** — halaman publik berbasis konten dari artboard
   Hardware (#3) dan Audio (#4). Calon user bisa preview cara pakai sebelum
   punya device.

### 4.2 Sistem audio + asset detection

Backend perlu dua endpoint kecil baru:

- `GET /audio/chimes/manifest.json` — return list file chime yang ada di
  `audio/chimes/`. Kalau folder kosong/tidak ada, return `{ "chimes": [] }`.
  Frontend `/guide` menggunakannya untuk menampilkan / menyembunyikan tombol
  "putar chime" di tiap baris.
- `GET /assets/manifest.json` — return list file gambar di `assets/`. Frontend
  memakainya untuk swap mockup SVG dengan foto asli kalau tersedia.

### 4.3 User preference — chime vs speech

Tambahkan field baru di `config.py` `_DEFAULTS`:

```python
"audio_mode": "both",   # "chime" | "speech" | "both"
```

Dan di `core/audio_manager.py`, pakai field ini untuk:

- `"chime"`  → hanya putar chime, skip semua TTS
- `"speech"` → hanya putar TTS, skip chime
- `"both"`  → chime dulu lalu speech (default — perilaku lama)

UI toggle ada di:

- Companion dashboard → kartu "Volume suara" (dropdown 3-pilihan)
- Setup wizard → ditambahkan sebagai sub-step di langkah 3
- Admin → sama dengan companion

---

## 5. Detail per-artboard

Lihat dokumen pendamping:

- **[ADMIN_SPEC.md](ADMIN_SPEC.md)** — bagaimana admin page mewarisi semua UI
  pendamping plus debug tools.
- **[USER_GUIDE_SPEC.md](USER_GUIDE_SPEC.md)** — halaman `/guide` publik yang
  menggabungkan Hardware + Audio menjadi panduan pakai.
- **[ASSETS_NEEDED.md](ASSETS_NEEDED.md)** — daftar gambar yang perlu dibuat
  di `assets/` + spesifikasi tiap gambar. Mockup SVG di prototype tetap dipakai
  sebagai fallback kalau file tidak ada.
- **[ACCESSIBILITY.md](ACCESSIBILITY.md)** — checklist WCAG 2.1 AA yang harus
  dipenuhi implementasi.

---

## 6. Screens / Views

### 6.1 `/` Companion Dashboard (`designs/companion-dashboard.jsx`)

**Layout — desktop ≥ 900px**

```
┌────────────────────────────────────────────────────┐
│  A11y bar (kontras / teks besar / kurangi animasi) │ 40px
├────────────────────────────────────────────────────┤
│  App header — logo • nav • status pill • avatar    │ 72px
├────────────────────────────────────────────────────┤
│  Status banner (HUGE, ok/danger color-coded)       │ 96px
├──────────────────────────────┬─────────────────────┤
│                              │                     │
│  Live view (camera+caption)  │  Mode switcher      │
│                              │  (3 big radio cards)│
│                              ├─────────────────────┤
│                              │  Volume slider      │
│                              │  (big +/- buttons)  │
│  Activity feed (today)       ├─────────────────────┤
│  - filter chips              │  Quick status grid  │
│  - timeline list             │  (batt/wifi/temp/AI)│
│  - export CSV                │                     │
├──────────────────────────────┴─────────────────────┤
│  Report problem + Call user + Power off (footer)   │
├────────────────────────────────────────────────────┤
│  Centered foot: version + link "Mode lanjutan"     │
└────────────────────────────────────────────────────┘
```

**Layout — mobile < 900px**

Single column, same order. Top status badges collapse to icon-only on header.

**Komponen** (semua di `designs/companion-dashboard.jsx`):

- `<StatusBanner>` — full-width, padding 20px 24px. Bg `var(--ok-soft)` saat
  online, `var(--danger-soft)` saat offline. Icon dalam lingkaran 56px.
- `<LiveView>` — kamera preview 16:9 + last caption block (border-left 6px
  accent, font 22px, bold).
- `<ModeSwitcher>` — `role="radiogroup"`, 3 tombol radio besar 72px tinggi
  dengan icon-circle + nama + sub + arrow.
- `<VolumeControl>` — slider range native + tombol +/- besar 48px + tombol
  "Mainkan suara percobaan".
- `<QuickStatus>` — grid 2×2 dengan baterai/wifi/suhu/cloud.
- `<ActivityFeed>` — list ordered, filter pill group (Semua/Jelajah/Deskripsi/
  QRIS/Sistem), waktu mono + icon-circle + caption + priority badge. Ada
  "Unduh log hari ini (CSV)".
- `<ReportFooter>` — tiga aksi: Lapor masalah, Panggil pengguna, Matikan device.
- `<A11yBar>` — kontras tinggi, teks besar, kurangi animasi. Live toggle.

### 6.2 `/setup` Setup Wizard (`designs/setup-wizard.jsx`)

4 langkah klikable di strip atas:

1. Hidupkan perangkat
2. Sambungkan WiFi (pilih SSID + password)
3. API key layanan AI (OpenAI / Gemini / Claude)
4. Uji & serahkan (checklist 5-item)

Tombol bawah: Kembali · Lewati · Lanjut. Saat di langkah 4, "Lanjut" jadi
"Selesai & kembali ke beranda" yang menutup wizard.

> Untuk admin: wizard tetap reachable kapan saja dari menu `/admin`. Untuk
> pendamping: hanya muncul saat first-time (cek flag `setup_completed` di
> config — kalau `false`, redirect ke wizard).

### 6.3 `/admin` Admin Dashboard

Lihat [ADMIN_SPEC.md](ADMIN_SPEC.md). Singkatnya: **embed seluruh Companion
dashboard di kolom utama**, lalu tambah kolom samping (collapsible) untuk
benchmark/log/AI settings.

### 6.4 `/guide` User Guide

Lihat [USER_GUIDE_SPEC.md](USER_GUIDE_SPEC.md). Halaman scroll panjang yang
isinya kombinasi artboard Hardware (`hardware-diagram.jsx`) + Audio
(`audio-spec.jsx`) + Storyboard (`storyboard.jsx`).

---

## 7. Design Tokens

Semua token ada di [`designs/tokens.css`](designs/tokens.css). Copy file ini ke
`device/server/static/tokens.css` dan import dari semua halaman.

**Highlights:**

| Token                  | Value                         | Catatan                                     |
| ---------------------- | ----------------------------- | ------------------------------------------- |
| `--bg`                 | `#F7F6F1`                     | Warm off-white                              |
| `--ink`                | `#141414`                     | 16.5:1 vs bg                                |
| `--accent`             | `#00635D`                     | Teal, 7.1:1                                 |
| `--ok / warn / danger` | `#1F6B3A / #8A5A00 / #B3261E` | Semua AA pada bg                            |
| `--t-base`             | `17px`                        | Body. **Minimum** 16px                      |
| `--hit`                | `48px`                        | Min hit-target (WCAG 2.1 AAA = 44, kita 48) |
| `--r-md`               | `10px`                        | Radius default                              |

**Variant** — toggle via `<html data-contrast="high">` dan `<html data-type="large">`.

---

## 8. Interactions & Behavior

### 8.1 Realtime data

Dashboard polls device tiap 500 ms (sama dengan dashboard lama). Endpoints
sudah ada:

- `GET /snapshot` → JPEG kamera
- `GET /status` → JSON `{ mode, detections, latency, battery, wifi_signal, temperature, audio_volume, last_caption }`

**Yang perlu ditambahkan ke `/status`:**

- `battery: int (0..100)` — kalau `i2c_battery_enabled=false`, return `null`,
  UI menampilkan ikon battery + label "(belum dikalibrasi)" tanpa angka.
- `wifi_signal: int (0..4)` — dari `iwconfig`.
- `wifi_ssid: str`
- `temperature: float` — sudah ada di health endpoint, expose juga di status.
- `last_caption: { text, time_iso, priority }` — caption suara terakhir.
- `audio_mode: "chime" | "speech" | "both"` — preference.

### 8.2 Ganti mode dari dashboard

`POST /command` sudah ada → `{ "cmd": "set_mode", "mode": "explorer" }`. UI
optimistic-update lalu wait response.

### 8.3 Volume

`POST /config { "audio_volume": 75 }` — sudah ada. UI debounce 200 ms saat
slider digerakkan.

### 8.4 Activity feed

`GET /history?date=today` — endpoint baru. Return:

```json
{
  "items": [
    { "t": "14:32", "mode": "explorer", "text": "...", "priority": "high" }
  ]
}
```

Source: rotated log files yang sudah ada di `/root/logs/`.

### 8.5 Asset & chime detection

```js
// On page load, both /guide and /companion
const [chimes, assets] = await Promise.all([
  fetch("/audio/chimes/manifest.json").then(r => r.ok ? r.json() : { chimes: [] }),
  fetch("/assets/manifest.json").then(r => r.ok ? r.json() : { assets: [] }),
]);
```

Backend (`device/server/routes.py`):

```python
@app.route("/audio/chimes/manifest.json")
def chimes_manifest():
    chimes_dir = Path(cfg.AUDIO_DIR) / "chimes"
    files = sorted(p.name for p in chimes_dir.glob("*.wav")) if chimes_dir.exists() else []
    return jsonify({"chimes": files})

@app.route("/assets/manifest.json")
def assets_manifest():
    assets_dir = Path("/root/assets")
    files = sorted(p.name for p in assets_dir.glob("*")) if assets_dir.exists() else []
    return jsonify({"assets": files})
```

### 8.6 Image fallback pattern

```jsx
function AssetImage({ name, fallback, alt, className }) {
  const url = window.__ASSETS__?.includes(name) ? `/assets/${name}` : null;
  return url
    ? <img src={url} alt={alt} className={className} />
    : fallback;  // the SVG mockup JSX
}
```

---

## 9. State Management

Untuk implementasi non-React (kemungkinan vanilla JS sesuai pola repo):

- **Server-truth** untuk: mode, volume, audio_mode, battery, wifi, temperature,
  detections, last_caption.
- **Client-only**: a11y prefs (kontras/big-text/motion), filter chip aktivitas,
  open/close menu mobile, modal state.
- **localStorage** untuk a11y prefs (`auralai.a11y.contrast`,
  `auralai.a11y.bigType`, `auralai.a11y.reduceMotion`).

---

## 10. Accessibility — WCAG 2.1 AA

Lihat [ACCESSIBILITY.md](ACCESSIBILITY.md). Ringkas:

- Semua kontras teks ≥ 4.5:1 sudah dipilih di tokens.
- Setiap kontrol punya hit-target 48×48px minimum.
- Setiap modal: focus-trap + Esc untuk close + restore focus.
- `aria-live="polite"` untuk: status banner, last caption, mode change result.
- `aria-live="assertive"` untuk: error toast, P0 danger announcements.
- Keyboard shortcut: `1/2/3` → Jelajah/Deskripsi/QRIS · `+/-` → volume ±10 · `?` → bantuan.
- Skip-link "Lewati ke konten utama" di top-of-page.
- `prefers-reduced-motion` dipatuhi + ada toggle manual.

---

## 11. Files

```
designs/
├── AuralAI Redesign.html   # design canvas — open this first
├── tokens.css              # SOURCE OF TRUTH for colors/type/spacing
├── icons.jsx               # SVG icon set (no emoji)
├── companion-dashboard.jsx # → port to /
├── setup-wizard.jsx        # → port to /setup
├── hardware-diagram.jsx    # → port into /guide
├── audio-spec.jsx          # → port into /guide
├── storyboard.jsx          # → port into /guide  
├── design-canvas.jsx       # canvas chrome (not for production)
└── tweaks-panel.jsx        # editor-only (not for production)
```

---

## 12. Suggested implementation order

1. **Copy `tokens.css` ke `device/server/static/`** dan link dari `index.html` lama.
2. **Implementasi `/guide` dulu** (no realtime, no auth) — proof-of-concept
   tokens + asset/chime detection.
3. **Implementasi setup wizard** — sederhana karena state lokal saja.
4. **Implementasi companion dashboard** — banyak realtime.
5. **Tambah `/admin`** — wrap companion + sisipkan panel lama di kolom samping.
6. **Backend additions** — `/history`, `/audio/chimes/manifest.json`,
   `/assets/manifest.json`, field tambahan di `/status`, `audio_mode` di config.
7. **Hardware (audio)** — tambah pembacaan chime file di `core/audio_manager.py`.

---

## 13. Out of scope

- Tidak mengubah inference loop (`core/ai_engine.py`).
- Tidak mengubah model YOLO atau provider AI.
- Tidak mengubah token autentikasi (sudah ada).
- Tidak mengganti companion PC (`companion/webserver.py`) — fokus device server.

---

## 14. Pertanyaan ke user (kalau ada)

- Confirm: device punya cukup storage untuk file chime + foto asset? (mungkin
  ~5 MB total — harusnya aman di SD card).
- Confirm: SSO/login admin masih pakai `device_token` lama?
- Confirm: bahasa selalu Indonesia, atau ada toggle ID/EN?

---

**Akhir handoff. Tanya saja kalau ada yang ambigu.**

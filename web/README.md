# I-Sora Web

Hub publik I-Sora, di-deploy ke Vercel. Next.js (App Router), Indonesia-first.

Tiga hal yang dilayani:

1. **Aplikasi (PWA) di `/app`** — daftar perangkat, pengaturan tiap perangkat,
   dan penambahan perangkat. Bisa dipasang ke layar utama ponsel.
2. **Simulasi kamera di `/simulasi`** — menjalankan alur I-Sora dengan kamera
   ponsel, tanpa perangkat. Berjalan offline setelah dibuka sekali.
3. **Situs publik** — landing, `/docs`, dan `/preview` (contoh suara).

## Pengembangan lokal

```bash
cd web
npm install
cp .env.example .env.local   # isi nilai bila perlu
npm run dev                  # http://localhost:3000
npm run build                # harus lolos sebelum deploy
npm run lint
```

> Kamera (`getUserMedia`) hanya jalan di **secure context**. `localhost` aman;
> untuk mencoba dari HP di LAN, pakai tunnel HTTPS (`vercel dev --listen`,
> `ngrok`, dsb.) atau langsung tes di deploy preview.

## Struktur

```
web/
  app/
    (marketing)/       Situs publik: landing, /docs, /preview, /login (opsional), /offline
    (shell)/           Aplikasi terpasang: /app, /app/[id], /app/tambah, /simulasi
    api/               Route handlers (relay device ↔ web)
    auth/              Callback & signout Supabase
    manifest.ts        Manifest PWA
    pair/, dashboard/  Redirect rute lama → /app/tambah dan /app
  components/          Nav, Footer, Notice, QrImage, InstallCard
    app/               Primitif gaya Settings (AppBar, SettingsGroup/Row, form perangkat)
  content/docs/        Markdown panduan (sumber halaman /docs)
  lib/
    sim/               Mesin simulator — port logika perangkat (lihat di bawah)
    devices.ts         Bentuk baris perangkat + turunan status
    net.ts             Deteksi "satu WiFi" (hash berkunci, bukan IP mentah)
    e2e.ts             Enkripsi API key ke pubkey perangkat
    pwa.ts             Registrasi service worker + prompt pemasangan
  public/
    sw.js              Service worker (shell, aset, cache model)
    icons/             Ikon PWA — regenerate: node scripts/gen-icons.mjs
  scripts/gen-icons.mjs
  supabase/schema.sql  Skema + RLS
```

## Dua route group

`app/(marketing)` memakai `Nav` + `Footer`; `app/(shell)` tidak — setiap layar
aplikasi membawa `AppBar`-nya sendiri, karena chrome marketing jadi gangguan
begitu I-Sora dipasang sebagai aplikasi standalone. Root `app/layout.tsx` hanya
berisi `<html>/<body>` dan registrasi service worker.

## Simulator (`lib/sim/`)

Port langsung dari kode perangkat supaya simulasi berbunyi seperti alat aslinya:

| File | Sumber di perangkat |
|---|---|
| `constants.ts` | `config.NAV_OBJECTS`, ambang di `config.py`, peta frasa di `core/audio_manager.py` |
| `vision.ts` | `utils/logger.position_from_bbox`, `utils/distance.band` |
| `announce.ts` | `utils/announce_policy.decide` |
| `detector.ts` | `core/ai_engine` (YOLO11n → COCO-SSD via TensorFlow.js) |
| `audio.ts` | `core/audio_manager` (WAV pra-render → WebAudio + Web Speech) |
| `qris.ts` | mode QRIS perangkat (BarcodeDetector, fallback jsQR) |
| `describe.ts` | mode Konteks (`utils/scene_prompt`, versi ringkas) |

Kalau angka di perangkat diubah, ubah juga di sini — itu satu-satunya alasan
simulasi ini layak dipercaya.

## Pairing

Tiga jalur, diurutkan dari yang paling sedikit usahanya:

1. **Otomatis** (`/api/pair/nearby`) — perangkat dan ponsel menjangkau relay
   dari IP publik yang sama, jadi hub bisa menampilkan perangkat yang belum
   tertaut "di sini". Ditawarkan hanya bila kandidatnya **tepat satu**, karena
   CGNAT bisa menyatukan beberapa rumah di satu IPv4.
2. **QR** (`/api/pair/qr` + `/api/pair/scan`) — kamera perangkat membaca token
   bertanda tangan dari layar ponsel. Tetap jalan lintas jaringan.
3. **Kode suara** (`/api/pair/code` + `/api/pair/claim`) — jalur terakhir.

Konstanta protokol `auralai-pair:` / `auralai-e2e-*` **tidak boleh di-rebrand**
— lihat `BRANDING.md`.

## Deploy ke Vercel

- Root directory: `web`
- Framework preset: Next.js (auto)
- Environment variables: lihat `.env.example`
  (`NEXT_PUBLIC_SITE_URL`, `NEXT_PUBLIC_SUPABASE_URL`,
  `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`,
  opsional `PAIR_SIGNING_SECRET`).

Jalankan ulang `supabase/schema.sql` setelah upgrade ini — ada kolom baru
`devices.net_hash` plus index dan grant kolom; skripnya idempotent.

Di Supabase → Authentication → Sign In / Providers, aktifkan:

- **Anonymous sign-ins** — **wajib**. Aplikasi tidak punya pendaftaran: membuka
  `/app` langsung membuat user anonim (`lib/supabase/session.ts`). Tanpa ini
  daftar perangkat tidak pernah muncul dan pairing selalu gagal.
- **Email (magic link)** — opsional, dipakai `/login` untuk menempelkan email ke
  user anonim yang sudah ada (`updateUser`), supaya perangkat bisa dibuka dari
  ponsel lain.

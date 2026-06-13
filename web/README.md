# I-Sora Web

Public hub untuk I-Sora: **pairing dengan kode suara**, **panduan/dokumentasi**,
dan **preview suara & chime**. Next.js (App Router), di-deploy ke Vercel.

## Pengembangan lokal

```bash
cd web
npm install
cp .env.example .env.local   # isi nilai bila perlu
npm run dev                  # http://localhost:3000
```

## Struktur

```
web/
  app/
    page.tsx              Landing
    docs/                 Panduan publik (render Markdown dari content/docs)
    preview/              Preview suara & chime (audio dari public/audio)
    pair/                 Halaman pairing (kode + QR)
    dashboard/            Daftar & pengaturan perangkat
    api/                  Route handlers (relay device ↔ web) — Fase 2+
  components/             Nav, Footer, QrSetup, DocsSidebar
  content/docs/           Markdown panduan (sumber halaman /docs)
  lib/                    i18n, docs loader, (Supabase — Fase 2)
  public/audio/           Contoh WAV untuk halaman preview
  supabase/               schema.sql + RLS — Fase 2
```

## Deploy ke Vercel

- Root directory: `web`
- Framework preset: Next.js (auto)
- Environment variables: lihat `.env.example`
  (`NEXT_PUBLIC_SITE_URL`, dan untuk Fase 2: `NEXT_PUBLIC_SUPABASE_URL`,
  `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`).

## Catatan arsitektur

Halaman ini HTTPS publik, jadi **tidak bisa** mengakses perangkat di LAN secara
langsung (mixed-content/CORS). Pengaturan dikirim ke perangkat lewat **relay cloud**:
perangkat membuka koneksi keluar (long-poll) dan menarik perintah. WiFi onboarding
tetap dilakukan lokal di perangkat. API key dienkripsi end-to-end ke perangkat.

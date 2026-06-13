# User Guide page — `/guide`

> Halaman publik (tanpa auth). Tujuan: calon pengguna, donatur, dosen pembimbing,
> dan keluarga bisa **preview cara pakai AuralAI tanpa punya device**.
>
> Konten dasar diambil dari dua artboard prototype: Hardware (#3) dan Audio (#4),
> plus Storyboard (#5) sebagai pengantar. Tapi disusun ulang sebagai halaman
> tunggal yang naratif (scroll panjang), bukan dashboard.

---

## 1. Struktur halaman (scroll top-to-bottom)

```
1. Hero
   ┌─────────────────────────────────────────────────────┐
   │ "AuralAI — kacamata yang menceritakan sekitarmu"    │
   │ Sub: penjelasan satu kalimat                         │
   │ [Coba demo audio]  [Lihat hardware]                  │
   │                                                     │
   │ Mockup glasses (SVG) atau foto produk asli          │
   │ kalau ada di assets/                                │
   └─────────────────────────────────────────────────────┘

2. "Bagaimana cara pakainya?" — Storyboard
   - 3 skenario (Jelajah / Deskripsi / QRIS)
   - Setiap skenario bisa di-expand untuk lihat panel detail
   - Default: tampilkan judul + panel #1 + tombol "Lanjut"

3. "Tombol di kacamatamu" — Hardware diagram
   - Hero diagram (samping + depan) — full width
   - Tabel 4 tombol — desktop 6-col, mobile collapsible accordion
   - Spec cards (4 cards: tactile, mounting, indikator, charging)

4. "Suara yang kamu akan dengar" — Audio guide
   - Priority hierarchy (4 cards)
   - Chime library (table dengan tombol "putar")
   - Pola getar
   - Aturan suara bicara

5. "Pilih cara mendengar"  — preference picker (CTA)
   ┌─────────────────────────────────────────────────────┐
   │ Mau dengar chime saja, suara bicara saja, atau      │
   │ keduanya?                                            │
   │                                                     │
   │ ◉ Chime + bicara (default)                          │
   │ ○ Hanya chime (cocok untuk pengguna mahir)          │
   │ ○ Hanya bicara (cocok untuk minggu pertama)         │
   │                                                     │
   │ [Simpan ke device saya]                             │
   └─────────────────────────────────────────────────────┘

6. "Mulai pakai" — link ke setup wizard / dokumentasi
```

---

## 2. Detail per section

### 2.1 Hero

- Background: gradient halus `--bg` → `--surface-2`
- Image slot: kalau `assets/hero_glasses.jpg` ada → `<img>`. Else → SVG mockup
  dari `hardware-diagram.jsx` (GlassesFront component).
- Type scale: h1 = `--t-3xl` (48px), sub = `--t-md` (19px).
- Layout: image kiri 1fr, copy kanan 1fr di desktop. Stack di mobile.

### 2.2 Storyboard section (reuse `storyboard.jsx`)

- Default: panel #1 saja per skenario. Tombol "Lihat semua panel" expand
  semuanya.
- Setiap panel pakai mockup SVG kecuali kalau `assets/scenario_<id>_<n>.jpg`
  ada (contoh `assets/scenario_1_3.jpg` untuk skenario 1 panel 3).

### 2.3 Hardware section (reuse `hardware-diagram.jsx`)

- Layout sama persis dengan artboard #3.
- `assets/glasses_front.jpg` & `assets/glasses_side.jpg` menggantikan SVG
  kalau ada. Kalau salah satunya saja yang ada → tetap pakai keduanya
  (mix SVG + foto, asal konsisten side-by-side).

### 2.4 Audio section (reuse `audio-spec.jsx`)

**Behavior penting:** tombol "Putar" di tabel chime conditional:

```js
const chimes = window.__CHIMES__;  // dari /audio/chimes/manifest.json
const hasChime = (id) => chimes.includes(`${id}.wav`);
```

- Kalau `hasChime("boot")` → tombol Play aktif, klik → `<audio>.play()` ke
  `/audio/chimes/boot.wav`
- Kalau tidak → tombol disabled dengan tooltip "Audio belum tersedia"
- **Visual shape (ChimeShape SVG) tetap tampil meskipun audio tidak ada** —
  user tetap bisa lihat bentuknya.

Atau lebih baik: kalau **tidak ada satupun chime** di manifest, hide kolom
"Putar" sama sekali agar tidak ada UI yang non-fungsional.

### 2.5 Preference picker

- 3 radio cards besar (`role="radiogroup"`).
- Saat klik "Simpan ke device saya" → `POST /config { "audio_mode": "..." }`.
- Kalau user **belum login** (tidak ada device_token), tombolnya berubah jadi
  "Salin link untuk pendamping" yang generates URL dengan `?audio_mode=both`
  query — pendamping nanti bisa apply di setup wizard.

---

## 3. SEO / metadata (opsional)

```html
<title>AuralAI — Cara Pakai Kacamata untuk Pengguna Tunanetra</title>
<meta name="description" content="Panduan visual & audio AuralAI...">
<meta property="og:image" content="/assets/og_cover.jpg">  <!-- fallback ke SVG -->
```

---

## 4. Routing

```python
@app.route("/guide")
def guide():
    return render_template_string(GUIDE_HTML)  # or serve static
```

No auth needed. Bandwidth/CPU murah karena static.

---

## 5. Mobile considerations

- Setiap tabel besar (button map, chime library) di mobile diubah jadi
  **accordion**: header = nama, expand = field lainnya.
- Hero image stack vertical, copy di bawahnya.
- Sticky bottom CTA "Mulai setup →" muncul setelah user scroll > 30%.

---

## 6. Empty-state behavior

| Asset folder kondisi               | Yang tampil                            |
| ---------------------------------- | -------------------------------------- |
| `assets/` kosong, `chimes/` kosong | Semua mockup SVG. Tombol play tabel chime hidden. Tampil banner kecil "Audio sample belum diupload". |
| `assets/` ada beberapa             | Mix SVG mockup + foto, per-image fallback. |
| `chimes/` ada sebagian             | Tombol play hanya pada chime yang punya file. |
| Keduanya lengkap                   | Full experience.                       |

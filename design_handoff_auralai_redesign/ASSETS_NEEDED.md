# Assets needed

> Letakkan file di folder `assets/` di project root (atau path yang sama dengan
> `audio/`). Frontend akan auto-detect via `/assets/manifest.json` dan ganti
> mockup SVG dengan file ini kalau tersedia.
>
> **Semua opsional** — kalau tidak ada, mockup SVG dari prototype tetap dipakai.
>
> File hilang TIDAK akan membuat halaman crash. Hanya menampilkan fallback.

---

## 1. Konvensi

- **Format**: `.jpg` (foto), `.png` (jika butuh transparency), `.svg` (jika
  iconography vektor)
- **Ukuran**: optimasi <300 KB per file. Pakai TinyPNG / Squoosh.
- **Ratio**: ditulis di tiap baris di bawah. Penting agar tidak crop salah.
- **Naming**: snake_case, prefix berdasarkan section.

---

## 2. Hero (halaman `/guide`)

| File                       | Ratio  | Deskripsi                                                                                 |
| -------------------------- | ------ | ----------------------------------------------------------------------------------------- |
| `assets/hero_glasses.jpg`  | 4:3    | Foto AuralAI dipasang di kacamata, ¾ angle, latar netral terang. Modul jelas terlihat di tangkai kanan. |
| `assets/og_cover.jpg`      | 1.91:1 | Versi landscape untuk social card. Sama kacamatanya tapi crop lebih luas + ada logo overlay kecil. |

---

## 3. Hardware diagram (artboard #3)

| File                         | Ratio       | Deskripsi                                                                                          |
| ---------------------------- | ----------- | -------------------------------------------------------------------------------------------------- |
| `assets/glasses_front.jpg`   | 480:280     | Foto kacamata tampak depan, modul di tangkai kanan. Background flat (white/off-white/foam board). Lensa harus reflektif sedikit supaya tidak hitam. |
| `assets/glasses_side.jpg`    | 360:320     | Foto kacamata tampak samping kanan, modul yang menempel kelihatan jelas. Tombol di sisi atas modul tampak. Bisa pakai macro / kacamata di-pegang oleh tangan. |
| `assets/button_power.jpg`    | 1:1         | Close-up tombol Power (bundar, recessed). Cukup zoomed in supaya tekstur cekungnya terlihat. |
| `assets/button_mode.jpg`     | 1:1         | Close-up tombol Mode dengan 3 titik braille di permukaan. |
| `assets/button_action.jpg`   | 1:1         | Close-up tombol Aksi (oval kuning menonjol). |
| `assets/button_volume.jpg`   | 1:1         | Close-up roda volume (gerigi tampak). |
| `assets/usbc_port.jpg`       | 1:1         | Close-up port USB-C di ujung bawah modul. Bisa dengan kabel terhubung. |
| `assets/mount_clip.jpg`      | 4:3         | Detail klip silikon menjepit tangkai. Sudut yang menunjukkan how-it-clips. |

> Kalau hanya bisa buat 2 file dari section ini, prioritaskan **glasses_front.jpg**
> dan **glasses_side.jpg** — keduanya yang paling berdampak.

---

## 4. Setup wizard (artboard #2)

| File                          | Ratio | Deskripsi                                                                |
| ----------------------------- | ----- | ------------------------------------------------------------------------ |
| `assets/setup_step1_boot.jpg` | 16:9  | Foto jari menekan tombol Power. LED indikator hijau menyala.             |
| `assets/setup_step4_handoff.jpg` | 16:9 | Foto pendamping memberikan kacamata ke pengguna tunanetra dengan senyum. Latar SLB / rumah. |

> Step 2 & 3 cukup pakai mockup karena isinya form, tidak butuh foto.

---

## 5. Storyboard (artboard #5)

> 3 skenario × ~5 panel = ~15 foto. **Prioritas: skenario 1** (paling sering dipakai).

### 5.1 Skenario 1 — Berjalan di koridor sekolah (`Jelajah`)

| File                            | Deskripsi                                                          |
| ------------------------------- | ------------------------------------------------------------------ |
| `assets/scenario_1_1.jpg`       | Pengguna keluar dari pintu kelas, koridor SLB, kacamata terpasang. |
| `assets/scenario_1_2.jpg`       | View dari pengguna: pintu di depan, kursi di pinggir.              |
| `assets/scenario_1_3.jpg`       | Orang lewat di kanan pengguna, jarak ~1 meter.                     |
| `assets/scenario_1_4.jpg`       | Close-up tangan pengguna menahan tombol Aksi.                      |
| `assets/scenario_1_5.jpg`       | POV menghadap tangga (turunan). Warning visual hint.              |

### 5.2 Skenario 2 — Mau makan di kantin (`Deskripsi`)

| File                            | Deskripsi                                                          |
| ------------------------------- | ------------------------------------------------------------------ |
| `assets/scenario_2_1.jpg`       | Pengguna menekan tombol Mode di tangkai kanan.                     |
| `assets/scenario_2_2.jpg`       | Pengguna menekan tombol Aksi sambil menghadap meja kantin.         |
| `assets/scenario_2_3.jpg`       | Meja kantin: piring nasi + air putih (foto top-down).              |
| `assets/scenario_2_4.jpg`       | HP guru menerima notifikasi "Panggilan dari Bu Sari".              |

### 5.3 Skenario 3 — Bayar di warung (`QRIS`)

| File                            | Deskripsi                                                          |
| ------------------------------- | ------------------------------------------------------------------ |
| `assets/scenario_3_1.jpg`       | Pengguna menekan Mode 2× — close-up tombol.                        |
| `assets/scenario_3_2.jpg`       | Pengguna menghadap kode QRIS, posisi belum tepat (sedikit miring). |
| `assets/scenario_3_3.jpg`       | QR berhasil terbaca — close-up frame QRIS di tangan warung.        |
| `assets/scenario_3_4.jpg`       | HP pengguna menampilkan layar konfirmasi pembayaran.              |
| `assets/scenario_3_5.jpg`       | Pengguna tersenyum, pembayaran selesai.                            |

---

## 6. Companion dashboard (`/`)

| File                                | Ratio | Deskripsi                                                  |
| ----------------------------------- | ----- | ---------------------------------------------------------- |
| `assets/sample_caption_view.jpg`    | 16:9  | Foto sample untuk "Live View" saat device offline / demo mode. Bisa foto koridor sekolah. |
| `assets/avatar_default.png`         | 1:1   | Default user avatar di header. Bisa ikon orang generik.    |

> Optional. Tanpa file ini, LiveView menampilkan SVG mockup + label "(Mode demo)".

---

## 7. Audio — chimes

> Folder: **`audio/chimes/`** (bukan `assets/`). Frontend detect via
> `/audio/chimes/manifest.json`.

Lihat tabel di [USER_GUIDE_SPEC.md](USER_GUIDE_SPEC.md) section 2.4 dan
prototype `audio-spec.jsx` untuk spesifikasi tiap chime.

| File                  | Bentuk | Nada       | Durasi  |
| --------------------- | ------ | ---------- | ------- |
| `boot.wav`            | rise   | C5 → G5    | 320 ms  |
| `mode-explorer.wav`   | single | G5         | 120 ms  |
| `mode-scene.wav`      | two    | G5 → C6    | 200 ms  |
| `mode-qris.wav`       | three  | C5–E5–G5   | 320 ms  |
| `listen.wav`          | blip   | E5         | 80 ms   |
| `thinking.wav`        | loop   | G4 (pulse) | 200ms/2s|
| `result-ok.wav`       | chord  | C5 + G5    | 200 ms  |
| `obstacle.wav`        | warn   | A4–C5 cepat| 180 ms  |
| `danger.wav`          | alarm  | C5 × 3     | 360 ms  |
| `low-batt.wav`        | drop   | C5 → E4    | 280 ms  |
| `no-net.wav`          | drop   | G4 → D4    | 240 ms  |
| `error.wav`           | buzz   | C4 tumpul  | 200 ms  |
| `sleep.wav`           | fade   | C5 → A4    | 600 ms  |

**Format**: WAV 16-bit PCM, 22.05 kHz mono. Total semua ≈ 200 KB.

> Bikinnya pakai BFXR/SFXR atau LMMS — ada beberapa sound designer yang
> familiar dengan UI earcons untuk accessibility. Catatan: hindari frekuensi
> < 200 Hz (speaker mungil tidak reproduce) dan > 6 kHz (tidak nyaman di
> kuping dekat).

---

## 8. Checklist prioritas

Kalau waktu terbatas, urutkan begini:

**Wave 1 (high impact, low effort)** — sekitar 1 jam pemotretan:
- [ ] `glasses_front.jpg`
- [ ] `glasses_side.jpg`
- [ ] `hero_glasses.jpg`
- [ ] Chime: `boot.wav`, `mode-explorer/scene/qris.wav`, `obstacle.wav`, `danger.wav`

**Wave 2 (medium impact)**:
- [ ] 4 button close-ups
- [ ] Skenario 1 full (5 foto)
- [ ] Sisa chime

**Wave 3 (polish)**:
- [ ] Skenario 2 & 3
- [ ] Setup wizard photos
- [ ] OG cover

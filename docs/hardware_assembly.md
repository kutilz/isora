# I-Sora — Panduan Rakit Hardware

Panduan merakit satu unit I-Sora: **MaixCAM + speaker mini + tombol + power**.
Perangkat ini untuk **pengguna tunanetra**, jadi **layar sudah dilepas** — semua
interaksi lewat **suara (speaker)** dan **dua tombol** (AKSI + MODE).

> **Baterai sengaja BELUM dipasang.** MaixCAM tidak bisa membaca kapasitas baterai
> tanpa modul fuel-gauge tambahan (lihat [§5](#5-baterai-ditunda)). Untuk sekarang,
> beri daya lewat **USB-C** saja.

---

## 1. Daftar komponen

| Komponen | Catatan |
|---|---|
| Sipeed MaixCAM (varian reguler) | Layar LCD sudah dilepas — tidak apa-apa, perangkat full-audio |
| Speaker mini 8Ω (≤2W) | Untuk output suara TTS + chime |
| Tombol push-button (momentary) × 2 | **AKSI** (capture/describe/scan) + **MODE** (ganti mode / alamat web) |
| Kabel USB-C + adaptor 5V (≥1A) | Sumber daya utama (pengganti baterai sementara) |
| Kabel jumper tipis / solder | Untuk speaker & tombol |

---

## 2. Power (USB-C 5V)

1. Colok **USB-C** dari adaptor 5V (atau power bank) ke port USB-C MaixCAM.
2. Perangkat langsung menyala — tidak ada tombol power terpisah yang wajib.
3. Setelah autostart aktif ([dokumen terpisah](#7-langkah-berikutnya)), MaixCAM
   otomatis menjalankan I-Sora saat dapat daya.

> Arus: pakai adaptor minimal **1A**. Saat kamera + NPU + WiFi aktif, konsumsi
> bisa naik; adaptor lemah bikin perangkat reboot sendiri.

---

## 3. Speaker mini

MaixCAM punya **amplifier audio onboard**. Speaker mini disambung ke **konektor /
pad speaker** di board:

1. Cari konektor speaker (`SPK`) atau pad **SPK+ / SPK-** di MaixCAM.
2. Sambungkan kabel speaker: **SPK+ → kabel merah**, **SPK- → kabel hitam**
   (polaritas speaker mini biasanya tidak kritis untuk suara mono).
3. Kalau speaker pakai konektor JST yang cocok, tinggal colok.

**Uji speaker:** setelah backend jalan, perangkat memutar chime objek (mis. saat
melihat orang/kursi). Kalau terdengar "orang di depan" dsb, speaker OK.

> Suara dinamis (deskripsi, baca QRIS, **pengumuman URL**) butuh paket **gTTS**
> ter-install di device — lihat [§6](#6-suara-dinamis-gtts).

---

## 4. Dua tombol (active-low, pull-up internal)

Perangkat pakai **2 tombol**: **AKSI** (capture sesuai permintaan) dan **MODE**
(ganti mode / alamat web). Driver GPIO mengaktifkan **pull-up internal**, jadi
**tombol mana pun cukup disambung active-low ke GND — tanpa resistor eksternal**.

> ⚠️ **Pad yang TIDAK BOLEH dipakai tombol** (terverifikasi di unit nyata, 2026-07-01):
>
> - **A14** — itu **LED onboard** MaixCAM; kernel meng-klaimnya sebagai output
>   (`led-user`), jadi tombol di A14 tidak akan pernah terbaca. (Versi lama
>   panduan ini menyarankan A14 — salah.)
> - **P18–P23** — itu bus **SDIO1 milik modul WiFi internal AIC8800**
>   (`mmc1` = `wifi-sd`). Tombol di sini tidak terbaca, dan tiap ditekan malah
>   men-short jalur data WiFi ke ground → WiFi bisa drop.
> - **A26** — pada varian board WiFi, **A26 = WiFi EN**; tombol di A26 bisa
>   mematikan/menyalakan WiFi tanpa sengaja.

**Pilihan pad (terverifikasi jalan):**

| Fungsi | Pad default | Catatan |
|---|---|---|
| **MODE** | **A28** | Sisi kanan (label `GPIOA 28 / UART2 TX`); aman selama UART2/JTAG tidak dipakai |
| **AKSI** | **A29** | Sisi kanan (label `GPIOA 29 / UART2 RX`); aman selama UART2/JTAG tidak dipakai |
| Alternatif | A22 / A23 / A24 / A25 | Boleh dipakai bila SPI4/eMMC tidak dipakai |

> ℹ️ **A15** seharusnya juga bisa, tapi pada unit #1 pad ini terukur *stuck LOW*
> (ketarik ke ground terus walau pull-up aktif) — kemungkinan short di
> solderan/board. Kalau mau pakai A15, cek dulu dengan multimeter: A15 ↔ GND
> harus **tidak** kontinyu saat tombol dilepas.

Enak-nya A28 + A29: keduanya bersebelahan di sisi kanan (hanya diselingi pad
`GPIOB 3/ADC`) dan dekat pad **GND** sisi kanan — kedua tombol bisa berbagi
ground yang sama.

**Wiring (per tombol):**

```
  Tombol MODE  kaki 1  ─────────  Pin A28 (MaixCAM)
  Tombol MODE  kaki 2  ─────────  GND
  Tombol AKSI  kaki 1  ─────────  Pin A29 (MaixCAM)
  Tombol AKSI  kaki 2  ─────────  GND
```

- Dilepas = pin HIGH (idle, ditahan pull-up internal). Ditekan = pin → GND = LOW
  (perangkat membaca "press"), lalu terdengar **chime tick** sebagai konfirmasi.
- Konfigurasi di `/root/config.json`:
  `"button_pin_mode": "A28"` dan `"button_pin_action": "A29"`.
  Mau ganti pad? Set nilai config ke nama pad-nya. Kosongkan (`""`) untuk nonaktif.
  Ganti pad butuh **restart app** — listener tombol hanya dibaca saat startup.

**Fungsi tombol AKSI:**

| Kondisi | Tekan sebentar | Tekan agak lama (≥1 dtk) |
|---|---|---|
| **Setup pertama** (URL belum di-ack) | — (nonaktif) | — (nonaktif) |
| **Mode Jelajah / Deskripsi** | Jelaskan apa yang di depan (1 tekan = 1 panggilan API) | Ucapkan ulang hasil terakhir |
| **Mode QRIS** | Pindai kode pembayaran | Ucapkan ulang hasil terakhir |

> Hemat token: gambar **hanya dikirim saat tombol AKSI ditekan** — tidak pernah
> streaming terus-menerus.

**Fungsi tombol MODE:**

| Kondisi | Tekan sebentar | Tekan agak lama (≥1 dtk) |
|---|---|---|
| **Setup pertama** (URL belum di-ack) | Ulangi pengumuman alamat web | "Sudah paham" → berhenti mengumumkan |
| **Pemakaian normal** | Ganti mode (Jelajah → Deskripsi → QRIS) | **Ucapkan ulang alamat web** |

> Jadi pengguna/pendamping selalu bisa dengar alamat webnya lagi kapan saja:
> tekan tombol **MODE agak lama**.

---

## 5. Baterai (ditunda)

MaixCAM **tidak meng-ekspose** data baterai (`/sys/class/power_supply` kosong —
sudah dicek di device ini). Artinya, untuk membaca **kapasitas/voltase** baterai
butuh **modul fuel-gauge I²C** tambahan, yang belum terpasang. Maka:

- **Sekarang:** jalankan dari USB-C, **konektor baterai dibiarkan kosong.**
- Backend sudah aman tanpa baterai: field `battery` di `/status` bernilai `null`
  dan tidak ada error (sudah diverifikasi).

**Nanti, kalau mau pakai baterai + bisa baca kapasitas:**

1. Pasang modul fuel-gauge I²C di bus I²C MaixCAM:
   - **INA219** (alamat `0x40`) — monitor arus + tegangan, atau
   - **MAX17043** (alamat `0x36`) — fuel gauge Li-Ion 1S.
2. Pakai sel **LiPo 1S** (3.7V nominal; aman 3.0–4.2V; stop ~3.3V under load).
3. Aktifkan pembacaan: `POST /i2c-probe` dari dashboard (atau set
   `i2c_battery_enabled: true`). Backend akan mulai mengisi `battery` di `/status`.

> Tanpa modul itu, jangan andalkan persentase baterai — pantau manual / pakai
> power bank dengan indikator sendiri.

---

## 6. Suara dinamis (gTTS)

Karena tidak ada layar, **suara adalah satu-satunya output**. Suara terbagi dua:

- **Chime objek** (118 file `.wav` siap pakai di `/root/audio`) — jalan offline.
- **Suara dinamis** (deskripsi scene, baca QRIS, **pengumuman alamat web**,
  "Isora siap") — disintesis via **gTTS** dan butuh internet sekali per kalimat
  (hasilnya di-cache di `/root/audio/tts_cache`).

**Install sekali per device** (butuh internet):

```bash
pip3 install -r /root/aural-ai/requirements_device.txt
# atau minimal:
pip3 install gtts
```

> Tanpa gTTS, semua kalimat dinamis akan **diam** (cuma chime objek yang bunyi).
> Ini wajib di-install supaya pengumuman URL & deskripsi berfungsi.

---

## 7. Cara tahu alamat web (tanpa layar)

Karena layar dilepas, alamat web ditemukan lewat **2 cara**:

1. **Nama tetap (mDNS):** perangkat tampil sebagai
   **`http://aural-bfe2.local:8080`** (nama unik dari MAC WiFi). Buka ini dari HP
   pendamping yang **satu WiFi**. Nama ini tetap walau IP DHCP berubah.
   - Untuk multi-device, tiap unit dapat nama beda otomatis (mis. `aural-1a2b`),
     jadi **5 perangkat tidak bentrok**. Bisa di-rename di wizard setup
     (mis. `dapur.local`, `kamar-budi.local`).
2. **Diucapkan speaker:** saat pertama nyala (dan setup belum selesai), perangkat
   **mengucapkan alamatnya** (IP + nama). Tekan tombol **sebentar** untuk ulang,
   **agak lama** untuk "sudah paham". Di pemakaian normal, tekan tombol **agak
   lama** kapan saja untuk dengar alamatnya lagi.

---

## 8. Langkah berikutnya

- **Autostart saat boot:** `python tools/run.py --host <ip> --autostart`
  (status: `--autostart-status`, batal: `--autostart-off`).
  > ⚙️ **Penting (device tanpa layar):** karena LCD dicopot, **launcher MaixApp
  > tidak bisa jalan**, jadi mekanisme `auto_start.txt` bawaan **tidak berfungsi**.
  > Tool ini otomatis pakai **`/etc/rc.local`** (dijalankan `/etc/init.d/S99local`
  > saat boot, setelah WiFi + avahi) — andal untuk app headless. Verifikasi: cabut-
  > colok, lalu cek `http://aural-bfe2.local:8080` hidup sendiri.
- **Setup pengguna baru:** buka `http://aural-bfe2.local:8080/setup`, isi WiFi +
  nama perangkat + API key AI, lalu "Selesai".
- **Catatan RAM (128 MB):** RAM ketat. Autostart lewat rc.local sengaja TIDAK
  menjalankan launcher GUI, jadi RAM-nya untuk app + kamera + YOLO. Hindari
  menjalankan proses berat lain bersamaan.

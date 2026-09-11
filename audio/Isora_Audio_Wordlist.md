# I-Sora — Daftar Audio Files (Full Scale)

> Format filename: `{kategori}_{deskripsi}.wav`  
> Bahasa: Indonesia  
> Engine: gTTS (`tts = gTTS(text=..., lang='id')`)  
> Total estimasi: ~350+ files

---

## 1. SISTEM — `system_`

### 1.1 Boot & Status
```
isora_menyala.wav             → "Isora menyala"
menghubungkan_ke_wifi.wav       → "Menghubungkan ke WiFi"
mode_ambil_data_aktif.wav       → "Mode ambil data aktif"
mengambil_data.wav              → "Mengambil data"
mode_normal_aktif.wav           → "Mode normal aktif"
atur_volume.wav                 → "Atur volume"
system_booting.wav              → "Isora sedang menyala"
system_ready.wav                → "Isora siap digunakan"
system_shutdown.wav             → "Isora dimatikan"
system_battery_low.wav          → "Baterai lemah, segera isi daya"
system_battery_critical.wav     → "Baterai kritis, perangkat akan mati"
system_battery_charging.wav     → "Sedang mengisi daya"
system_error.wav                → "Terjadi kesalahan"
system_no_camera.wav            → "Kamera tidak terdeteksi"
system_overheating.wav          → "Perangkat terlalu panas"
```

### 1.2 Koneksi
```
system_wifi_connected.wav       → "WiFi terhubung"
system_wifi_disconnected.wav    → "WiFi terputus"
system_4g_connected.wav         → "Jaringan seluler terhubung"
system_4g_disconnected.wav      → "Jaringan seluler terputus"
system_no_internet.wav          → "Tidak ada koneksi internet"
```

### 1.3 Mode
```
system_mode_explorer.wav        → "Mode penjelajah aktif"
system_mode_context.wav         → "Mode konteks aktif"
system_mode_qris.wav            → "Mode scan bayar aktif"
system_mode_currency.wav        → "Mode deteksi uang aktif"
system_mode_switching.wav       → "Mengganti mode"
```

### 1.4 Proses
```
system_processing.wav           → "Sedang memproses"
system_analyzing.wav            → "Sedang menganalisis"
system_capturing.wav            → "Mengambil gambar"
system_please_wait.wav          → "Harap tunggu sebentar"
system_done.wav                 → "Selesai"
system_failed.wav               → "Gagal, coba lagi"
system_no_result.wav            → "Tidak ada hasil yang terdeteksi"
system_try_again.wav            → "Coba arahkan kamera lebih jelas"
```

---

## 2. NAVIGASI & BAHAYA — `nav_`

### 2.1 Peringatan Umum
```
nav_warning.wav                 → "Peringatan"
nav_danger_ahead.wav            → "Bahaya di depan"
nav_stop.wav                    → "Berhenti"
nav_caution.wav                 → "Hati-hati"
nav_clear.wav                   → "Jalur aman"
```

### 2.2 Posisi (9 zona grid)
```
nav_pos_left.wav                → "di sebelah kiri"
nav_pos_right.wav               → "di sebelah kanan"
nav_pos_center.wav              → "di depan"
nav_pos_top_left.wav            → "di kiri atas"
nav_pos_top_center.wav          → "di atas"
nav_pos_top_right.wav           → "di kanan atas"
nav_pos_bottom_left.wav         → "di kiri bawah"
nav_pos_bottom_center.wav       → "di bawah"
nav_pos_bottom_right.wav        → "di kanan bawah"
```

### 2.3 Jarak & Ukuran
```
nav_very_close.wav              → "sangat dekat"
nav_close.wav                   → "dekat"
nav_medium.wav                  → "jarak sedang"
nav_far.wav                     → "jauh"
nav_approaching.wav             → "semakin mendekat"
nav_moving_away.wav             → "bergerak menjauh"
```

---

## 3. OBJEK DETEKSI — `obj_`

> Pola kalimat: "{objek} {posisi} {jarak}"  
> Karena digabung secara programatik, yang perlu dibuat hanya nama objeknya saja sebagai potongan audio, lalu digabung dengan audio posisi & jarak.

### 3.1 Kendaraan
```
obj_motorcycle.wav              → "motor"
obj_car.wav                     → "mobil"
obj_truck.wav                   → "truk"
obj_bus.wav                     → "bus"
obj_bicycle.wav                 → "sepeda"
obj_becak.wav                   → "becak"
obj_gerobak.wav                 → "gerobak"
obj_vehicle_moving.wav          → "kendaraan bergerak"
```

### 3.2 Manusia
```
obj_person.wav                  → "orang"
obj_crowd.wav                   → "banyak orang"
obj_child.wav                   → "anak kecil"
```

### 3.3 Penghalang & Infrastruktur
```
obj_chair.wav                   → "kursi"
obj_table.wav                   → "meja"
obj_door.wav                    → "pintu"
obj_stairs_up.wav               → "tangga naik"
obj_stairs_down.wav             → "tangga turun"
obj_pole.wav                    → "tiang"
obj_wall.wav                    → "dinding"
obj_pothole.wav                 → "lubang"
obj_step.wav                    → "undakan"
obj_bump.wav                    → "polisi tidur"
obj_puddle.wav                  → "genangan air"
obj_construction.wav            → "area konstruksi"
```

### 3.4 Hewan
```
obj_dog.wav                     → "anjing"
obj_cat.wav                     → "kucing"
obj_animal.wav                  → "hewan"
```

### 3.5 Barang Umum
```
obj_bottle.wav                  → "botol"
obj_bag.wav                     → "tas"
obj_phone.wav                   → "ponsel"
obj_cup.wav                     → "cangkir"
obj_food.wav                    → "makanan"
```

---

## 4. UANG RUPIAH — `currency_`

### 4.1 Nominal Kertas
```
currency_1000.wav               → "seribu rupiah"
currency_2000.wav               → "dua ribu rupiah"
currency_5000.wav               → "lima ribu rupiah"
currency_10000.wav              → "sepuluh ribu rupiah"
currency_20000.wav              → "dua puluh ribu rupiah"
currency_50000.wav              → "lima puluh ribu rupiah"
currency_100000.wav             → "seratus ribu rupiah"
```

### 4.2 Nominal Koin
```
currency_coin_100.wav           → "koin seratus rupiah"
currency_coin_200.wav           → "koin dua ratus rupiah"
currency_coin_500.wav           → "koin lima ratus rupiah"
currency_coin_1000.wav          → "koin seribu rupiah"
```

### 4.3 Status Deteksi
```
currency_detected.wav           → "Uang terdeteksi"
currency_not_detected.wav       → "Uang tidak terdeteksi, coba dekatkan"
currency_multiple.wav           → "Terdeteksi beberapa uang, pisahkan satu per satu"
currency_unclear.wav            → "Gambar tidak jelas, coba perbaiki pencahayaan"
currency_front.wav              → "sisi depan"
currency_back.wav               → "sisi belakang"
```

---

## 5. QRIS & PEMBAYARAN — `qris_`

### 5.1 Status Scan
```
qris_scanning.wav               → "Sedang memindai kode pembayaran"
qris_detected.wav               → "Kode pembayaran terdeteksi"
qris_not_detected.wav           → "Kode pembayaran tidak ditemukan"
qris_not_qris.wav               → "Ini bukan kode QRIS"
qris_unclear.wav                → "Kode tidak terbaca, coba dekatkan kamera"
qris_too_far.wav                → "Terlalu jauh, dekatkan ke kode"
```

### 5.2 Konfirmasi Transaksi
```
qris_merchant_prefix.wav        → "Nama merchant:"
qris_amount_prefix.wav          → "Nominal:"
qris_confirm.wav                → "Apakah Anda ingin melanjutkan pembayaran?"
qris_success.wav                → "Pembayaran berhasil"
qris_cancelled.wav              → "Pembayaran dibatalkan"
qris_warning_amount.wav         → "Perhatikan nominal sebelum membayar"
```

### 5.3 Angka (untuk nominal pembayaran — digabung programatik)
```
num_0.wav      → "nol"
num_1.wav      → "satu"
num_2.wav      → "dua"
num_3.wav      → "tiga"
num_4.wav      → "empat"
num_5.wav      → "lima"
num_6.wav      → "enam"
num_7.wav      → "tujuh"
num_8.wav      → "delapan"
num_9.wav      → "sembilan"
num_10.wav     → "sepuluh"
num_100.wav    → "ratus"
num_1000.wav   → "ribu"
num_10000.wav  → "puluh ribu"
num_100000.wav → "ratus ribu"
num_1000000.wav → "juta"
```

---

## 6. CONTEXT MODE — `ctx_`

### 6.1 Trigger & Status
```
ctx_capturing.wav               → "Mengambil gambar untuk dianalisis"
ctx_sending.wav                 → "Mengirim ke server"
ctx_describing.wav              → "Sedang mendeskripsikan"
ctx_result_prefix.wav           → "Hasil analisis:"
ctx_no_description.wav          → "Tidak dapat mendeskripsikan gambar ini"
ctx_api_error.wav               → "Gagal terhubung ke server analisis"
```

> Catatan: Hasil dari OpenAI API di-TTS secara real-time menggunakan gTTS online, jadi tidak perlu pre-generate untuk response-nya. Yang di-pre-generate hanya kalimat prefix & status di atas.

---

## 7. TOMBOL & INTERAKSI — `ui_`

```
ui_button_explorer.wav          → "Tombol mode penjelajah"
ui_button_context.wav           → "Tombol mode konteks"
ui_button_qris.wav              → "Tombol scan bayar"
ui_button_currency.wav          → "Tombol cek uang"
ui_button_describe.wav          → "Tombol deskripsi"
ui_volume_up.wav                → "Volume naik"
ui_volume_down.wav              → "Volume turun"
ui_mute.wav                     → "Suara dimatikan"
ui_unmute.wav                   → "Suara dinyalakan"
ui_help.wav                     → "Panduan penggunaan"
```

---

## 8. PANDUAN SINGKAT — `help_`

```
help_intro.wav                  → "Isora membantu Anda mengenali objek, uang, dan kode pembayaran"
help_explorer.wav               → "Mode penjelajah: perangkat akan memberitahu objek di sekitar Anda"
help_context.wav                → "Mode konteks: tekan tombol untuk mendeskripsikan pemandangan secara detail"
help_qris.wav                   → "Mode scan bayar: arahkan kamera ke kode pembayaran untuk verifikasi"
help_currency.wav               → "Mode uang: arahkan kamera ke uang kertas untuk mengetahui nominalnya"
help_touch.wav                  → "Ketuk sekali untuk berganti mode, ketuk dua kali untuk aktifkan analisis"
```

---

## Ringkasan Jumlah File

| Kategori | Jumlah File |
|----------|------------|
| system_  | ~25 |
| nav_     | ~16 |
| obj_     | ~28 |
| currency_| ~19 |
| qris_    | ~11 |
| num_     | ~16 |
| ctx_     | ~6 |
| ui_      | ~10 |
| help_    | ~6 |
| **Total** | **~137 files** |

---

## Catatan Generate Script

```python
# tools/generate_audio.py — contoh pola
from gtts import gTTS
import os

audio_list = {
    "system_ready": "Isora siap digunakan",
    "obj_motorcycle": "motor",
    "nav_pos_left": "di sebelah kiri",
    # dst...
}

output_dir = "../audio"
os.makedirs(output_dir, exist_ok=True)

for filename, text in audio_list.items():
    path = os.path.join(output_dir, f"{filename}.wav")
    tts = gTTS(text=text, lang='id', slow=False)
    tts.save(path)
    print(f"Generated: {filename}.wav")
```

> gTTS menghasilkan MP3 secara default. Untuk konversi ke WAV, tambahkan `pydub`:
> ```python
> from pydub import AudioSegment
> mp3 = AudioSegment.from_mp3(mp3_path)
> mp3.export(wav_path, format="wav")
> ```
> Install ffmpeg di PC sebelum menjalankan script.

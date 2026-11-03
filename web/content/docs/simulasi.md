---
title: Simulasi dengan kamera HP
order: 5
summary: Coba cara kerja I-Sora tanpa perangkat — kamera ponsel, chime arah, dan suara Indonesia.
---

# Simulasi dengan kamera HP

Halaman **[Simulasi kamera](/simulasi)** menjalankan alur I-Sora di ponsel:
kamera belakang jadi mata, dan ponsel berbicara persis seperti perangkat.

Gunanya dua: calon pengguna bisa merasakan dulu sebelum punya perangkat, dan
pendamping bisa berlatih membaca isyarat suaranya.

## Cara memakai

1. Buka **[Simulasi kamera](/simulasi)** — lewat aplikasi, menu **Coba & pelajari**.
2. Ketuk **Mulai simulasi**, lalu izinkan akses kamera.
3. Pakai **earphone**. Arah kiri/kanan disampaikan lewat panning stereo, jadi
   lewat speaker ponsel isyarat arahnya hilang.
4. Arahkan kamera ke sekitar dan dengarkan.

## Tombol di layar

| Tombol | Yang terjadi |
|---|---|
| **Ulangi** | Bacakan ulang semua yang terlihat sekarang |
| **Jelaskan** | Jelaskan sekitar dengan AI |

## Mode

- **Penjelajah** — menyebut objek dan arahnya, seperti pemakaian sehari-hari.
- **QRIS** — membaca kode pembayaran dan menyebutkan nama merchant-nya.
  Hanya membaca; simulasi tidak pernah melakukan pembayaran.

## Cara mendengar

Sama seperti pengaturan di perangkat:

- **Chime + bicara** — bunyi pendek berarah, lalu kalimatnya.
- **Hanya chime** — untuk yang sudah hafal bunyinya; jauh lebih cepat.
- **Hanya bicara** — untuk yang baru mulai.

## Jelaskan sekitar

Tombol **Jelaskan** mengirim **satu gambar** ke layanan AI lewat
server I-Sora. Tidak perlu daftar atau mengisi apa pun. Fitur ini aktif pukul
12.50–15.30 WIB.

## Offline

Setelah dibuka sekali, model deteksi tersimpan di ponsel dan simulasi berjalan
**tanpa internet** — sama seperti perangkat aslinya. Yang tetap butuh internet
hanya "Jelaskan sekitar", karena memanggil layanan AI.

Pasang halaman ini sebagai aplikasi (**Pasang di layar utama**) supaya bisa
dibuka langsung dari ikon.

## Seberapa mirip dengan perangkat aslinya?

Yang **sama persis** — diambil dari kode perangkat:

- daftar objek yang diumumkan dan sebutan Indonesianya;
- pembagian arah 3×3 (kiri, tengah, kanan, atas, bawah, dan sudut-sudutnya);
- ambang "dekat" per jenis objek, dorongan kalau benda menyentuh lantai, dan
  pita histeresis supaya benda di batas tidak bolak-balik;
- aturan kapan harus bersuara: hanya saat ada perubahan, dengan pengulangan
  berkala untuk bahaya, jeda antar-ucapan, dan batas jumlah per frame.

Yang **berbeda**:

- Perangkat memakai YOLO11n di NPU-nya; ponsel memakai COCO-SSD lewat
  TensorFlow.js. Ruang labelnya sama, tapi ketelitiannya bisa berbeda.
- Sebagian besar ucapan memakai suara yang sama dengan perangkat: kalimat objek,
  arah, dan pesan sistem sudah direkam sebelumnya, lalu disimpan di ponsel
  setelah simulasi dibuka sekali. Jawaban AI dan nama merchant QRIS direkam
  saat itu juga, jadi bagian ini butuh internet.
- Chime di simulasi dibangkitkan langsung di browser, jadi nadanya tidak sama
  dengan chime perangkat.

## Panel debug

Nyalakan **Tampilkan detail teknis** untuk melihat kotak deteksi, label, tier
`near`/`far`, nilai `area_ratio`, dan lama inferensi. Berguna untuk demo,
laporan, atau memastikan logikanya berperilaku seperti di perangkat.

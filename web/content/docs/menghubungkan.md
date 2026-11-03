---
title: Menghubungkan perangkat
order: 3
summary: Tiga cara menautkan perangkat — otomatis lewat WiFi, pindai QR, atau kode suara. Tanpa daftar akun.
---

# Menghubungkan perangkat

Setelah perangkat tersambung ke WiFi, buka aplikasi I-Sora di ponsel — halaman
**[I-Sora](/app)** — lalu pilih **Tambah perangkat**.

**Tidak ada pendaftaran.** Aplikasi langsung bisa dipakai; perangkat yang
dihubungkan tersimpan di ponsel itu. Email hanya ditawarkan belakangan, dan
sifatnya opsional — lihat [Memakai di ponsel lain](#memakai-di-ponsel-lain).

Ada beberapa cara, diurutkan dari yang paling sedikit usahanya.

## Cara 1 — Tekan tombol perangkat (utama)

Buka **Tambah perangkat**. Halaman itu langsung menunggu, dan perangkat
mengucapkan:

> "Isora siap. Untuk menghubungkan, buka isora strip smartglasses titik vercel
> titik app di ponsel, pilih tambah perangkat, lalu **tekan tombol aksi** pada
> alat ini sekali."

Tekan tombol **ACTION** sekali. Selesai — tanpa mengetik, tanpa melihat layar,
tanpa perlu orang lain membacakan apa pun.

Perangkat langsung menjawab dengan suara supaya hasilnya langsung diketahui:

| Yang terdengar | Artinya |
|---|---|
| "Perangkat sudah terhubung." | Berhasil |
| "Belum ada ponsel yang menunggu…" | Halaman Tambah perangkat belum terbuka |
| "Ada lebih dari satu ponsel yang menunggu…" | Tutup salah satunya, tekan lagi |
| "Belum ada internet…" | Perangkat belum tersambung WiFi |

> **Kenapa tombol?** Yang menekan tombol adalah orang yang sedang memegang
> alatnya — itu bukti kepemilikan yang lebih kuat daripada sekadar "satu WiFi",
> dan tidak menuntut apa pun dari orang yang tidak bisa melihat layar.

Berlaku di jaringan mana pun; perangkat tidak harus satu WiFi dengan ponsel.

## Cara 2 — Ketuk dari daftar (kalau satu WiFi)

Kalau ponsel dan perangkat tersambung ke **WiFi yang sama**, perangkat baru juga
muncul sendiri di halaman itu. Ketuk **"Hubungkan perangkat ini"** — sedikit
lebih cepat daripada menekan tombol, karena namanya sudah terlihat.

> **Kenapa bisa tahu?** Perangkat dan ponsel keluar ke internet lewat router
> yang sama, jadi keduanya terlihat dari alamat publik yang sama. Server hanya
> menyimpan sidik ringkasnya, bukan alamatnya.

Kalau di jaringan itu ada **lebih dari satu** perangkat baru sekaligus (misalnya
di kelas atau kantor), daftar ini sengaja tidak muncul — kami tidak bisa menebak
mana yang dimaksud. Tombolnya tetap jalan; tekan saja.

## Cara 3 — Pindai QR dengan kamera perangkat

Cadangan kalau tombol ACTION rusak.

1. Buka **Tambah perangkat → Pindai QR dengan kamera perangkat**.
2. Sebuah kode QR muncul di layar ponsel.
3. **Arahkan kamera perangkat I-Sora ke layar itu**, sekitar sejengkal jauhnya.
4. Perangkat menautkan dirinya sendiri, lalu terdengar
   "Perangkat sudah terhubung".

> Kode QR berisi token yang **kedaluwarsa dalam beberapa menit** dan hanya
> berlaku untuk ponsel yang menampilkannya.

Cara ini tetap jalan meski ponsel dan perangkat beda jaringan.

## Cara 4 — Ketik kode suara

Cara lama, **tidak diucapkan lagi** sejak cara tombol ada: mengetik enam karakter
yang harus didengar dulu adalah hal paling merepotkan dari semua cara di sini,
justru bagi orang yang paling butuh alat ini.

Kodenya masih dibuat dan masih berlaku di halaman **Tambah perangkat → Ketik kode
suara** (sekali pakai, kedaluwarsa 10 menit), tapi perangkat tidak menyebutkannya
sendiri. Praktisnya cara ini hanya relevan kalau seseorang membacanya dari log
perangkat.

## Kalau tidak ada internet sama sekali

Perangkat tidak butuh internet untuk bekerja. Bila cloud tidak terjangkau, ia akan
menyebutkan alamat lokalnya sendiri:

> "Isora siap digunakan. Untuk membuka panel kontrol, sambungkan ponsel ke
> jaringan WiFi yang sama, lalu buka alamat: satu nol titik … port 8080."

Buka alamat itu di browser ponsel dan atur langsung dari perangkat.

> **Catatan:** nama `.local` (misalnya `isora-bfe2.local`) sering **tidak bisa
> dibuka di HP Android** karena Chrome Android tidak menerjemahkan nama `.local`.
> Kalau begitu, pakai alamat IP yang juga diucapkan perangkat.

## Mengatur setelah terhubung

Begitu tertaut, layar pengaturan perangkat terbuka:

- **Nama perangkat** — dipakai juga sebagai alamat lokalnya di WiFi.
- **Layanan AI** — OpenAI, Gemini, atau Claude, lalu API key-nya.
- **Cara mendengar** — chime saja, bicara saja, atau keduanya.
- **Kendali lokal** — tautan ke panel tombol di perangkat, muncul ketika
  ponsel berada di WiFi yang sama.

Tekan **Simpan & selesai**. Layar sambutan I-Sora muncul dan memberi tahu
keadaannya: *"Mengirim pengaturan ke perangkat…"* lalu *"Pengaturan sudah
diterima perangkat."* Setelah itu layar berpindah sendiri ke halaman perangkat.
Kalau perangkat sedang mati atau belum kembali online, layar itu bilang apa
adanya — pengaturan tetap tersimpan dan masuk sendiri begitu perangkat
tersambung lagi.

> **Privasi:** API key dienkripsi di browser dan hanya bisa dibuka oleh
> perangkat tersebut. Server kami tidak pernah menyimpan key asli.

### Kalau halaman penyiapan keburu tertutup

Tidak apa-apa, dan tidak perlu diulang dari awal. Penautan sudah selesai di
perangkat begitu tombolnya ditekan; yang tersisa hanya pengaturannya.

Buka lagi **[I-Sora](/app)**. Perangkat yang belum selesai disiapkan muncul
dengan titik **kuning** dan keterangan *"perlu disiapkan"* — ketuk untuk
melanjutkan dari tempat yang sama. Halaman **Tambah perangkat** juga
menampilkannya di bagian paling atas.

> Jangan menekan tombol ACTION lagi untuk "mengulang": perangkat sudah tertaut
> dan akan menjawab *"Perangkat ini sudah terhubung."*

## Lebih dari satu perangkat

Satu ponsel boleh memegang banyak perangkat. Semuanya tampil di layar utama aplikasi
dengan status masing-masing; ketuk salah satu untuk mengaturnya. Beri nama yang
berbeda (misalnya `isora-rumah` dan `isora-sekolah`) supaya mudah dibedakan —
nama itu juga yang dipakai sebagai alamat lokalnya.

## Memakai di ponsel lain

Daftar perangkat tersimpan di peramban ponsel ini. Kalau data peramban
dihapus, atau ingin membuka perangkat yang sama dari ponsel/laptop lain,
tambahkan email sekali:

1. Buka **I-Sora → Cadangan → Tambahkan email**.
2. Klik tautan yang masuk ke inbox — **buka di peramban yang sama**.
3. Di perangkat lain, buka `/login` dan masukkan email yang sama.

Perangkat yang sudah tertaut ikut terbawa; tidak perlu dihubungkan ulang.

## Melepaskan perangkat

Di layar pengaturan perangkat, pilih **Lepaskan perangkat**. Perangkat tetap
berfungsi seperti biasa; ia hanya bisa dihubungkan lagi dari mana pun.

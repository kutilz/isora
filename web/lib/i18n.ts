/**
 * Indonesian-first strings for the public web hub.
 * Mirrors the device UI vocabulary (device/server/src/i18n/id.json) so the
 * web and the on-device dashboard speak the same language to the user.
 */

export const t = {
  app: "I-Sora",
  tagline: "Melihat dengan Suara",
  nav: {
    home: "Beranda",
    app: "Aplikasi",
    sim: "Simulasi",
    docs: "Panduan",
    preview: "Coba suara",
  },
  hero: {
    badge: "Bisa dicoba tanpa perangkat",
    title: "Melihat dengan suara — coba dulu dari kamera ponselmu",
    lead:
      "Arahkan kamera HP ke sekitarmu dan dengarkan apa yang akan dikatakan I-Sora. Sudah punya perangkatnya? Pasang aplikasi ini untuk menghubungkan dan mengaturnya.",
    cta_sim: "Coba simulasi kamera",
    cta_app: "Buka aplikasi",
    cta_docs: "Baca panduan",
  },
  features: {
    title: "Apa yang bisa dilakukan di sini",
    items: [
      {
        title: "Simulasi kamera HP",
        body:
          "Deteksi objek, chime berarah, dan suara Indonesia — berjalan sepenuhnya di ponsel. Setelah dibuka sekali, jalan tanpa internet.",
      },
      {
        title: "Aplikasi yang bisa dipasang",
        body:
          "Pasang di layar utama, lalu buka langsung dari ikon. Menghubungkan perangkat cukup sekali tekan tombol — tanpa mengetik alamat atau kode.",
      },
      {
        title: "Banyak perangkat, tanpa daftar akun",
        body:
          "Buka aplikasinya dan langsung pakai — tidak ada pendaftaran. Lihat status tiap perangkat, atur layanan AI dan preferensi suaranya, dan buka kendali lokalnya saat kamu berada di WiFi yang sama.",
      },
    ],
  },
  how: {
    title: "Tiga langkah menghubungkan",
    steps: [
      "Nyalakan perangkat dan sambungkan ke WiFi rumah (lihat panduan).",
      "Buka aplikasi di ponsel, pilih Tambah perangkat — tanpa daftar akun.",
      "Tekan tombol aksi pada perangkat sekali. Selesai; lalu atur layanan AI dan preferensi suara.",
    ],
    fallback:
      "Tombolnya berlaku di jaringan mana pun. Kalau ponsel dan perangkat satu WiFi, perangkat juga muncul sendiri di daftar dan cukup diketuk.",
  },
  privacy: {
    title: "Privasi tetap dijaga",
    body:
      "API key dienkripsi di browser dan hanya bisa dibuka oleh perangkatmu — server kami tidak pernah melihat key aslinya. Kamera tidak pernah dialirkan ke cloud; hanya status ringkas (online, baterai, mode) yang dikirim, plus sidik ringkas jaringan agar aplikasi tahu kapan kamu berada di WiFi yang sama.",
  },
  footer: {
    made: "I-Sora — Melihat dengan Suara. Teknologi asistif berbasis suara untuk teman netra di Indonesia.",
    offline: "Perangkat tetap berfungsi penuh secara offline; web ini hanya untuk setup, pemantauan, dan simulasi.",
    wcag: "Tampilan web ini sengaja sederhana dan kontras tinggi, mengikuti pedoman aksesibilitas WCAG 2.1 tingkat AA, supaya nyaman bagi pengguna low vision dan pembaca layar.",
  },
};

export type Strings = typeof t;

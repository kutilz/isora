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
    pair: "Hubungkan",
    docs: "Panduan",
    preview: "Coba suara",
    dashboard: "Perangkat saya",
  },
  hero: {
    badge: "Setup tanpa ribet",
    title: "Hubungkan I-Sora cukup dengan satu kode suara",
    lead:
      "Perangkat menyebutkan sebuah kode singkat. Buka halaman ini, masukkan kodenya, lalu atur semuanya dari ponsel — tanpa perlu mengeja alamat IP.",
    cta_pair: "Hubungkan perangkat",
    cta_docs: "Baca panduan",
  },
  features: {
    title: "Kenapa lewat web ini?",
    items: [
      {
        title: "Pairing dengan kode suara",
        body:
          "Perangkat mengucapkan kode unik. Masukkan di sini untuk menautkannya ke akunmu — aman dan singkat.",
      },
      {
        title: "Atur dari mana saja",
        body:
          "Pilih layanan AI, masukkan API key, dan sesuaikan suara langsung dari halaman ini. Perubahan terdorong otomatis ke perangkat.",
      },
      {
        title: "Panduan & contoh suara",
        body:
          "Pelajari cara memakai I-Sora dan dengarkan contoh chime sebelum perangkat tiba — semuanya online, bukan cuma di perangkat.",
      },
    ],
  },
  how: {
    title: "Tiga langkah menghubungkan",
    steps: [
      "Nyalakan perangkat dan sambungkan ke WiFi rumah (lihat panduan).",
      "Dengarkan kode yang diucapkan perangkat, lalu masukkan di halaman Hubungkan.",
      "Atur layanan AI dan preferensi suara — perangkat langsung menerima pengaturannya.",
    ],
  },
  privacy: {
    title: "Privasi tetap dijaga",
    body:
      "API key dienkripsi di browser dan hanya bisa dibuka oleh perangkatmu — server kami tidak pernah melihat key aslinya. Kamera tidak pernah dialirkan ke cloud; hanya status ringkas (online, baterai, mode) yang dikirim.",
  },
  footer: {
    made: "I-Sora — Melihat dengan Suara. Teknologi asistif berbasis suara untuk teman netra di Indonesia.",
    offline: "Perangkat tetap berfungsi penuh secara offline; web ini hanya untuk setup & pemantauan.",
  },
};

export type Strings = typeof t;

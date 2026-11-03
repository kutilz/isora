import type { MetadataRoute } from "next";

/**
 * PWA manifest. `start_url` points at the Settings app rather than the landing
 * page: once I-Sora is installed the user wants their devices, not marketing.
 * The landing page stays reachable in a normal browser tab.
 */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "I-Sora — Melihat dengan Suara",
    short_name: "I-Sora",
    description:
      "Atur perangkat I-Sora dan coba simulasi kamera langsung dari ponsel — bisa dipakai offline.",
    lang: "id",
    dir: "ltr",
    start_url: "/app",
    scope: "/",
    display: "standalone",
    orientation: "portrait",
    background_color: "#F7F3EC",
    theme_color: "#2C3680",
    categories: ["utilities", "medical", "productivity"],
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icons/icon-maskable-192.png", sizes: "192x192", type: "image/png", purpose: "maskable" },
      { src: "/icons/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
    shortcuts: [
      {
        name: "Simulasi kamera",
        short_name: "Simulasi",
        description: "Coba cara kerja I-Sora dengan kamera ponsel.",
        url: "/simulasi",
        icons: [{ src: "/icons/icon-192.png", sizes: "192x192" }],
      },
      {
        name: "Perangkat saya",
        short_name: "Perangkat",
        description: "Status dan pengaturan perangkat I-Sora.",
        url: "/app",
        icons: [{ src: "/icons/icon-192.png", sizes: "192x192" }],
      },
    ],
  };
}

import type { Metadata, Viewport } from "next";
import { Plus_Jakarta_Sans, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import PwaBoot from "@/components/PwaBoot";

// Variable, with no weight list: for a list of static weights Google Fonts now
// answers with file URLs that have no extension, and next/font crashes on them.
const sans = Plus_Jakarta_Sans({
  subsets: ["latin"],
  variable: "--font-jakarta",
  display: "swap",
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "700"],
  variable: "--font-jetbrains",
  display: "swap",
});

export const metadata: Metadata = {
  title: "I-Sora — Melihat dengan Suara",
  description:
    "Atur perangkat I-Sora dari ponsel dan coba simulasinya dengan kamera HP — pasang sebagai aplikasi, bisa dipakai offline.",
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000"),
  manifest: "/manifest.webmanifest",
  applicationName: "I-Sora",
  appleWebApp: {
    capable: true,
    title: "I-Sora",
    statusBarStyle: "default",
  },
  icons: {
    icon: [
      { url: "/icons/icon.svg", type: "image/svg+xml" },
      { url: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
    ],
    apple: "/icons/apple-touch-icon.png",
  },
};

export const viewport: Viewport = {
  themeColor: "#2C3680",
  // The simulator draws a full-bleed camera view; let it reach the edges.
  viewportFit: "cover",
};

/**
 * Root shell only. The public site (Nav + Footer) and the installed app shell
 * are separate route groups — app/(marketing) and app/(app) — because the
 * marketing chrome is noise once I-Sora is running as a standalone PWA.
 */
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="id" className={`${sans.variable} ${mono.variable}`}>
      <body>
        <PwaBoot />
        {children}
      </body>
    </html>
  );
}

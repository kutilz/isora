import type { Metadata } from "next";
import BukuReader from "./BukuReader";

export const metadata: Metadata = {
  title: "Buku Panduan & Buku Audio — I-Sora",
  description:
    "Versi digital dan buku audio Manual Book I-SORA: keselamatan, tombol dan mode, mengisi daya, dan kalau ada masalah. Bisa didengar dan dibaca pembaca layar.",
};

/** Target of the QR code printed in the Manual Book (front + back cover). */
export default function BukuPage() {
  return <BukuReader />;
}

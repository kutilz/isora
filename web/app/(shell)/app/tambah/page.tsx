import { Suspense } from "react";
import AddClient from "./AddClient";
import RelayPausedScreen from "@/components/app/RelayPaused";
import { RELAY_PAUSED } from "@/lib/relay";

export const metadata = {
  title: "Tambah perangkat — I-Sora",
  description: "Hubungkan perangkat I-Sora ke aplikasi: otomatis lewat WiFi, pindai QR, atau kode suara.",
};

export default function AddDevicePage() {
  if (RELAY_PAUSED) return <RelayPausedScreen title="Tambah perangkat" />;
  return (
    <Suspense fallback={<div className="app-body">Memuat…</div>}>
      <AddClient />
    </Suspense>
  );
}

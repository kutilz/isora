import { Suspense } from "react";
import DeviceClient from "./DeviceClient";
import RelayPausedScreen from "@/components/app/RelayPaused";
import { RELAY_PAUSED } from "@/lib/relay";

export const metadata = {
  title: "Pengaturan perangkat — I-Sora",
  description: "Status, pengaturan, dan kendali lokal satu perangkat I-Sora.",
};

export default async function DevicePage({ params }: { params: Promise<{ id: string }> }) {
  if (RELAY_PAUSED) return <RelayPausedScreen title="Perangkat" />;
  const { id } = await params;
  return (
    <Suspense fallback={<div className="app-body">Memuat…</div>}>
      <DeviceClient id={id} />
    </Suspense>
  );
}

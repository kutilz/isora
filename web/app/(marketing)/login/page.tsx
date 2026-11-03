import { Suspense } from "react";
import LoginClient from "./LoginClient";
import { RelayPausedLinks, RelayPausedNotice } from "@/components/app/RelayPaused";
import { RELAY_PAUSED } from "@/lib/relay";

export const metadata = { title: "Cadangkan ke email — I-Sora" };

export default function LoginPage() {
  if (RELAY_PAUSED) {
    return (
      <div className="container section" style={{ maxWidth: 560 }}>
        <h1>Cadangkan ke email</h1>
        <RelayPausedNotice />
        <RelayPausedLinks />
      </div>
    );
  }
  return (
    <Suspense fallback={<div className="container section">Memuat…</div>}>
      <LoginClient />
    </Suspense>
  );
}

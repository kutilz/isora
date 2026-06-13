import { Suspense } from "react";
import LoginClient from "./LoginClient";

export const metadata = { title: "Masuk — I-Sora" };

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="container section">Memuat…</div>}>
      <LoginClient />
    </Suspense>
  );
}

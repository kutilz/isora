"use client";

import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { createClient } from "@/lib/supabase/client";
import Notice from "@/components/Notice";

export default function LoginClient() {
  const params = useSearchParams();
  const next = params.get("next") || "/dashboard";
  // /auth/callback redirects here with ?error= when a magic link is bad/expired
  const authFailed = !!params.get("error");
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    setBusy(true);
    try {
      const supabase = createClient();
      const redirectTo = `${window.location.origin}/auth/callback?next=${encodeURIComponent(next)}`;
      const { error } = await supabase.auth.signInWithOtp({
        email: email.trim(),
        options: { emailRedirectTo: redirectTo },
      });
      if (error) throw error;
      setSent(true);
    } catch (e: any) {
      setErr(e?.message || "Gagal mengirim tautan. Coba lagi.");
    } finally {
      setBusy(false);
    }
  };

  const shownErr =
    err ||
    (authFailed
      ? "Tautan masuk tidak valid atau sudah kedaluwarsa. Masukkan email untuk menerima tautan baru."
      : "");

  return (
    <div className="container section" style={{ maxWidth: 460 }}>
      <h1 style={{ fontSize: "var(--t-2xl)", letterSpacing: "-.02em" }}>Masuk</h1>
      <p className="sub">
        Kami kirim tautan ajaib ke emailmu — tanpa password. Klik tautannya untuk masuk.
      </p>

      {sent ? (
        <Notice kind="ok">
          Tautan masuk sudah dikirim ke <strong>{email}</strong>. Cek inbox (dan folder spam).
        </Notice>
      ) : (
        <form onSubmit={submit} className="card" style={{ display: "grid", gap: "var(--s-4)" }}>
          <div className="field">
            <label htmlFor="email">Email</label>
            <input
              id="email"
              className="input"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="kamu@contoh.com"
              autoComplete="email"
            />
          </div>
          {shownErr && <Notice kind="err">{shownErr}</Notice>}
          <button className="btn btn--primary btn--lg" type="submit" disabled={busy || !email}>
            {busy ? "Mengirim…" : "Kirim tautan masuk"}
          </button>
        </form>
      )}
    </div>
  );
}

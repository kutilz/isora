"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { ensureSession, type Session } from "@/lib/supabase/session";
import Notice from "@/components/Notice";

/**
 * There is no sign-up. This page does one of two jobs depending on what the
 * browser already has:
 *
 *   anonymous session → attach an email to *that same user* (updateUser), so the
 *                       devices already paired here come along.
 *   no session        → a plain magic link, which is how a second phone gets
 *                       access to devices paired on the first one.
 *
 * Either way it is optional: /app works without ever visiting this page.
 */
export default function LoginClient() {
  const params = useSearchParams();
  const next = params.get("next") || "/app";
  // /auth/callback redirects here with ?error= when a link is bad or expired.
  const authFailed = !!params.get("error");

  const [session, setSession] = useState<Session | null>(null);
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    ensureSession().then((s) => alive && setSession(s));
    return () => {
      alive = false;
    };
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    setBusy(true);
    try {
      const supabase = createClient();
      const redirectTo = `${window.location.origin}/auth/callback?next=${encodeURIComponent(next)}`;
      const target = email.trim();

      if (session?.kind === "ok" && session.anonymous) {
        // Upgrade in place — same user id, so ownership rows stay valid.
        const { error } = await supabase.auth.updateUser({ email: target }, { emailRedirectTo: redirectTo });
        if (error) throw error;
      } else {
        const { error } = await supabase.auth.signInWithOtp({
          email: target,
          options: { emailRedirectTo: redirectTo },
        });
        if (error) throw error;
      }
      setSent(true);
    } catch (e) {
      setErr((e as Error)?.message || "Gagal mengirim tautan. Coba lagi.");
    } finally {
      setBusy(false);
    }
  };

  const alreadyLinked = session?.kind === "ok" && !session.anonymous;
  const upgrading = session?.kind === "ok" && session.anonymous;

  const shownErr =
    err ||
    (authFailed
      ? "Tautan tidak valid atau sudah kedaluwarsa. Masukkan email untuk menerima tautan baru."
      : "");

  return (
    <div className="container section" style={{ maxWidth: 460 }}>
      <h1 style={{ fontSize: "var(--t-2xl)", letterSpacing: "-.02em" }}>Cadangkan ke email</h1>
      <p className="sub">
        {upgrading
          ? "Perangkatmu sudah tersimpan di ponsel ini. Tambahkan email supaya bisa dibuka dari ponsel lain — dan tidak hilang kalau data peramban dihapus."
          : "Masukkan email yang sama dengan yang kamu pakai di ponsel lain. Kami kirim tautan ajaib — tanpa password."}
      </p>

      {alreadyLinked ? (
        <Notice kind="ok">
          Sudah tercadangkan ke <strong>{session.email}</strong>.{" "}
          <Link href="/app">Kembali ke aplikasi</Link>
        </Notice>
      ) : sent ? (
        <Notice kind="ok">
          Tautan sudah dikirim ke <strong>{email}</strong>. Cek inbox (dan folder spam), lalu buka
          tautannya <strong>di peramban ini</strong>.
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
            {busy ? "Mengirim…" : "Kirim tautan"}
          </button>
          <p className="hint" style={{ margin: 0 }}>
            Opsional. <Link href="/app">Lewati</Link> — aplikasi tetap jalan tanpa ini.
          </p>
        </form>
      )}
    </div>
  );
}

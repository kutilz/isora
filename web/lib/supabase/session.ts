"use client";

import type { User } from "@supabase/supabase-js";
import { createClient } from "./client";

/**
 * The app has no sign-up step: opening /app is enough.
 *
 * Ownership still hangs off `auth.users` exactly as before — RLS, the
 * column-level grants and every route handler are untouched. The only thing
 * that changed is where the identity comes from: instead of sending the user to
 * type an email, the browser is handed an *anonymous* Supabase user on the spot.
 *
 * Adding an email later (/login) upgrades that same user via `updateUser()`, so
 * its id — and therefore every device already paired to it — survives.
 *
 * The trade-off, stated plainly: the session lives in this browser's storage.
 * Clearing site data, or picking up a different phone, loses the device list and
 * the device has to be paired again. Pairing is one tap on the same WiFi, so
 * that is a cheap loss — and the optional email upgrade removes it entirely.
 *
 * Needs "Allow anonymous sign-ins" enabled in Supabase → Authentication →
 * Sign In / Providers. Without it every call returns `none` with the reason, and
 * the UI says so instead of silently showing an empty list.
 */

export type Session =
  | { kind: "ok"; id: string; email: string | null; anonymous: boolean }
  | { kind: "none"; reason: string };

function describe(user: User): Session {
  return {
    kind: "ok",
    id: user.id,
    email: user.email ?? null,
    // `is_anonymous` rides on the JWT. Fall back to "has no email" for sessions
    // minted before the claim existed.
    anonymous: user.is_anonymous ?? !user.email,
  };
}

async function resolve(): Promise<Session> {
  let supabase: ReturnType<typeof createClient>;
  try {
    // Throws synchronously when the Supabase env vars are unset.
    supabase = createClient();
  } catch {
    return { kind: "none", reason: "Relay belum dikonfigurasi." };
  }

  try {
    // getSession() reads local state; the server re-validates the cookie on
    // every API call anyway, so there is no reason to pay a round-trip here.
    const { data } = await supabase.auth.getSession();
    const existing = data.session?.user;
    if (existing) return describe(existing);

    const { data: made, error } = await supabase.auth.signInAnonymously();
    if (error || !made.user) {
      return { kind: "none", reason: error?.message || "Tidak bisa membuat sesi." };
    }
    return describe(made.user);
  } catch (e) {
    return { kind: "none", reason: (e as Error)?.message || "Tidak ada koneksi." };
  }
}

/**
 * The session for this browser, creating an anonymous one if there is none.
 *
 * Concurrent callers share one attempt — three screens mounting at once must not
 * race to mint three different anonymous users, which would scatter the paired
 * devices across identities.
 */
let inflight: Promise<Session> | null = null;

export function ensureSession(): Promise<Session> {
  if (!inflight) {
    inflight = resolve().finally(() => {
      inflight = null;
    });
  }
  return inflight;
}

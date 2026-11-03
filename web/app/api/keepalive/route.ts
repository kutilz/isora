import { NextResponse } from "next/server";
import { createAdminClient } from "@/lib/supabase/admin";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Daily touch of the database (vercel.json `crons`). A free Supabase project is
 * paused after 7 quiet days, and a paused project's hostname stops resolving:
 * /app then dies with "Failed to fetch" and no device can pair. This happened
 * in October 2026 while no unit was online, so the relay must not depend on
 * devices for its own liveness. Also a cheap health probe: 200 = relay up.
 */
export async function GET() {
  try {
    const { error } = await createAdminClient().from("devices").select("id", { head: true, count: "exact" }).limit(1);
    if (error) throw error;
    return NextResponse.json({ ok: true, at: new Date().toISOString() });
  } catch (e: unknown) {
    // PostgrestError is a plain object, not an Error.
    const msg = (e as { message?: string })?.message || String(e);
    return NextResponse.json({ ok: false, error: msg.slice(0, 200) }, { status: 503 });
  }
}

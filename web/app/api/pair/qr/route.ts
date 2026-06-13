import { NextResponse } from "next/server";
import { createServerSupabase } from "@/lib/supabase/server";
import { signClaimToken } from "@/lib/pair-token";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Browser (logged in) requests a QR claim token. The token is rendered as a QR
 * for the device camera to scan. Stateless — signed, expires in a few minutes.
 */
export async function POST() {
  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "not signed in" }, { status: 401 });

  const token = signClaimToken(user.id);
  return NextResponse.json({ token, value: `auralai-pair:${token}` });
}

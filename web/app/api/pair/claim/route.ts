import { NextResponse } from "next/server";
import { createServerSupabase } from "@/lib/supabase/server";
import { createAdminClient } from "@/lib/supabase/admin";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Browser claims a device with the spoken code. Requires a logged-in user.
 * Validates the code (exists, unused, unexpired), links the device to the user,
 * and burns the code. Body: { code }
 */
export async function POST(req: Request) {
  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "not signed in" }, { status: 401 });

  let body: any;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid json" }, { status: 400 });
  }
  const code = String(body.code || "").trim().toUpperCase();
  if (!code) return NextResponse.json({ error: "code required" }, { status: 400 });

  const admin = createAdminClient();
  const { data: row } = await admin
    .from("pairing_codes")
    .select("code, device_id, expires_at, used")
    .eq("code", code)
    .maybeSingle();

  if (!row || row.used || new Date(row.expires_at).getTime() < Date.now()) {
    return NextResponse.json({ error: "kode tidak valid atau kedaluwarsa" }, { status: 400 });
  }

  // Burn the code and link ownership (service role — bypasses RLS).
  await admin.from("pairing_codes").update({ used: true }).eq("code", code);
  const { data: device, error } = await admin
    .from("devices")
    .update({ owner_user_id: user.id })
    .eq("id", row.device_id)
    .select("id, name, pubkey, fw_version")
    .maybeSingle();
  if (error || !device) {
    return NextResponse.json({ error: "gagal menautkan perangkat" }, { status: 500 });
  }

  return NextResponse.json({ ok: true, device });
}

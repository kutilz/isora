import { NextResponse } from "next/server";
import { createServerSupabase } from "@/lib/supabase/server";
import { createAdminClient } from "@/lib/supabase/admin";
import { networkHash, sameNetwork } from "@/lib/net";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** Device detail incl. pubkey (for client-side E2E). RLS restricts to owner. */
export async function GET(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "not signed in" }, { status: 401 });

  const { data, error } = await supabase
    .from("devices")
    .select("id, name, pubkey, fw_version, status, last_seen, created_at, net_hash")
    .eq("id", id)
    .maybeSingle();
  if (error) return NextResponse.json({ error: "query failed" }, { status: 500 });
  if (!data) return NextResponse.json({ error: "not found" }, { status: 404 });

  // Same contract as /api/devices: expose the verdict, never the stored hash.
  const { net_hash, ...device } = data;
  return NextResponse.json({
    device: { ...device, same_network: sameNetwork(networkHash(req), net_hash) },
  });
}

/** Unlink a device from the account (does not wipe anything on the device). */
export async function DELETE(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "not signed in" }, { status: 401 });

  // Ownership check under RLS first — the row comes back only if it's theirs.
  const { data: owned } = await supabase.from("devices").select("id").eq("id", id).maybeSingle();
  if (!owned) return NextResponse.json({ error: "not found" }, { status: 404 });

  // The write itself needs the service role: the owner UPDATE policy re-checks
  // `owner_user_id = auth.uid()` on the NEW row, so a user can never null it out
  // themselves. Releasing the device lets it be paired again; nothing on the
  // device is wiped, and queued commands die with the cascade.
  const admin = createAdminClient();
  const { error } = await admin.from("devices").update({ owner_user_id: null }).eq("id", id);
  if (error) return NextResponse.json({ error: "unlink failed" }, { status: 500 });

  return NextResponse.json({ ok: true });
}

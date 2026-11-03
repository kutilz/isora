import { NextResponse } from "next/server";
import { createServerSupabase } from "@/lib/supabase/server";
import { createAdminClient } from "@/lib/supabase/admin";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Has the device applied a queued command yet?
 *
 * The device ACK deletes the row (so E2E ciphertext does not linger), which
 * makes "row gone" the success signal. The app polls this so it can say
 * "diterima perangkat" instead of a dead "terkirim" that leaves the person
 * wondering whether anything happened at all.
 *
 * Query: ?command_id=<uuid>
 */
export async function GET(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const commandId = (new URL(req.url).searchParams.get("command_id") || "").trim();
  // Guarded because a malformed uuid makes Postgres reject the filter, and a
  // failed query would otherwise look exactly like "the row is gone" = applied.
  if (!UUID_RE.test(commandId)) {
    return NextResponse.json({ error: "command_id required" }, { status: 400 });
  }

  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "not signed in" }, { status: 401 });

  // Ownership check under RLS — returns the row only if the user owns it.
  const { data: owned } = await supabase.from("devices").select("id").eq("id", id).maybeSingle();
  if (!owned) return NextResponse.json({ error: "not found" }, { status: 404 });

  // commands_owner_select scopes this read to devices the caller owns.
  const { data, error } = await supabase
    .from("commands")
    .select("id")
    .eq("id", commandId)
    .eq("device_id", id)
    .maybeSingle();
  if (error) return NextResponse.json({ error: "query failed" }, { status: 500 });

  return NextResponse.json({ status: data ? "pending" : "applied" });
}

/**
 * Queue a config command for a device the user owns. Plain settings go in
 * `config`; secrets (API keys) arrive already E2E-encrypted to the device pubkey
 * in `secrets` and are relayed as opaque ciphertext (deleted after ACK).
 *
 * Body: { config?: object, secrets?: object }
 */
export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "not signed in" }, { status: 401 });

  // Ownership check under RLS — returns the row only if the user owns it.
  const { data: owned } = await supabase.from("devices").select("id").eq("id", id).maybeSingle();
  if (!owned) return NextResponse.json({ error: "not found" }, { status: 404 });

  let body: any;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid json" }, { status: 400 });
  }
  const config = body.config && typeof body.config === "object" ? body.config : {};
  const secrets = body.secrets && typeof body.secrets === "object" ? body.secrets : {};
  if (!Object.keys(config).length && !Object.keys(secrets).length) {
    return NextResponse.json({ error: "nothing to update" }, { status: 400 });
  }

  const admin = createAdminClient();
  const { data, error } = await admin
    .from("commands")
    .insert({ device_id: id, type: "config", payload: { config, secrets } })
    .select("id")
    .maybeSingle();
  if (error) return NextResponse.json({ error: "queue failed" }, { status: 500 });

  return NextResponse.json({ ok: true, command_id: data?.id });
}

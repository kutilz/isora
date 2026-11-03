import { NextResponse } from "next/server";
import { createServerSupabase } from "@/lib/supabase/server";
import { networkHash, sameNetwork } from "@/lib/net";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * List the signed-in user's devices (RLS restricts to owned rows).
 *
 * Each row carries `same_network`: true when this browser reaches us from the
 * same public IP as the device's last heartbeat, i.e. they share a WiFi. The
 * app uses it to decide whether the device's plain-HTTP LAN control page is
 * actually openable. The stored hash itself never leaves the server.
 */
export async function GET(req: Request) {
  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "not signed in" }, { status: 401 });

  const { data, error } = await supabase
    .from("devices")
    .select("id, name, fw_version, status, last_seen, created_at, net_hash")
    .order("created_at", { ascending: true });
  if (error) return NextResponse.json({ error: "query failed" }, { status: 500 });

  const mine = networkHash(req);
  const devices = (data ?? []).map(({ net_hash, ...d }) => ({
    ...d,
    same_network: sameNetwork(mine, net_hash),
  }));

  return NextResponse.json({ devices });
}

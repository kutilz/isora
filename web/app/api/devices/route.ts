import { NextResponse } from "next/server";
import { createServerSupabase } from "@/lib/supabase/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** List the signed-in user's devices (RLS restricts to owned rows). */
export async function GET() {
  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "not signed in" }, { status: 401 });

  const { data, error } = await supabase
    .from("devices")
    .select("id, name, fw_version, status, last_seen, created_at")
    .order("created_at", { ascending: true });
  if (error) return NextResponse.json({ error: "query failed" }, { status: 500 });

  return NextResponse.json({ devices: data ?? [] });
}

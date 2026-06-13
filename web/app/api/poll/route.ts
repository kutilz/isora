import { NextResponse } from "next/server";
import { createAdminClient } from "@/lib/supabase/admin";
import { authDevice } from "@/lib/device";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
// Long-poll window. Vercel caps this per plan (Hobby ≈ 10s, Pro ≈ 60s+).
export const maxDuration = 30;

const WINDOW_MS = Number(process.env.POLL_WINDOW_MS || 25_000);
const STEP_MS = 1_500;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * Device long-polls for the next pending command. Returns the command as soon as
 * one appears, or 204 after the window elapses (device immediately re-polls).
 * Auth via device headers.
 */
export async function GET(req: Request) {
  const auth = await authDevice(req);
  if (!auth.ok) return NextResponse.json({ error: auth.error }, { status: auth.status });

  const admin = createAdminClient();
  const deadline = Date.now() + WINDOW_MS;

  do {
    const { data } = await admin
      .from("commands")
      .select("id, type, payload, created_at")
      .eq("device_id", auth.deviceId)
      .eq("status", "pending")
      .order("created_at", { ascending: true })
      .limit(1)
      .maybeSingle();

    if (data) {
      return NextResponse.json({ command: data });
    }
    if (Date.now() + STEP_MS >= deadline) break;
    await sleep(STEP_MS);
  } while (Date.now() < deadline);

  return new NextResponse(null, { status: 204 });
}

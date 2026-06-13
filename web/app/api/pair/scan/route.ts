import { NextResponse } from "next/server";
import { createAdminClient } from "@/lib/supabase/admin";
import { authDevice } from "@/lib/device";
import { verifyClaimToken } from "@/lib/pair-token";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Device submits a claim token it scanned from the browser's QR. Authenticated
 * as the device (X-Device-Id/Secret); the token proves which user account to
 * link. Body: { token }
 */
export async function POST(req: Request) {
  const auth = await authDevice(req);
  if (!auth.ok) return NextResponse.json({ error: auth.error }, { status: auth.status });

  let body: any;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid json" }, { status: 400 });
  }
  let token = String(body.token || "").trim();
  if (token.startsWith("auralai-pair:")) token = token.slice("auralai-pair:".length);

  const claim = verifyClaimToken(token);
  if (!claim) return NextResponse.json({ error: "kode QR tidak valid atau kedaluwarsa" }, { status: 400 });

  const admin = createAdminClient();
  const { error } = await admin
    .from("devices")
    .update({ owner_user_id: claim.uid })
    .eq("id", auth.deviceId);
  if (error) return NextResponse.json({ error: "gagal menautkan perangkat" }, { status: 500 });

  return NextResponse.json({ ok: true, paired: true });
}

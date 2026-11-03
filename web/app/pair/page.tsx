import { redirect } from "next/navigation";

/**
 * Legacy entry point. The device's spoken sentence and the printed docs point
 * at /pair, and the old typed-code deep link carried ?code=… — keep both
 * working by forwarding into the app's "Tambah perangkat" screen.
 */
export default async function LegacyPairPage({
  searchParams,
}: {
  searchParams: Promise<{ code?: string }>;
}) {
  const { code } = await searchParams;
  redirect(code ? `/app/tambah?code=${encodeURIComponent(code)}` : "/app/tambah");
}

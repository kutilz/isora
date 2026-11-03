import { redirect } from "next/navigation";

/** The device list now lives in the app shell. */
export default function LegacyDashboardPage() {
  redirect("/app");
}

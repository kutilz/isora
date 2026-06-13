import DashboardClient from "./DashboardClient";

export const metadata = {
  title: "Perangkat saya — I-Sora",
  description: "Pantau dan atur perangkat I-Sora yang sudah terhubung.",
};

export default function DashboardPage() {
  return <DashboardClient />;
}

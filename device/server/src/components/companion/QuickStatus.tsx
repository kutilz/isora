import { Icon } from "../atoms/Icon";
import type { DeviceStatus } from "./types";
import { t } from "../../lib/i18n";

export function QuickStatus({ status }: { status: DeviceStatus | null }) {
  const battery = status?.battery;
  const batteryTone =
    battery == null ? "info" :
    battery >= 40   ? "ok" :
    battery >= 15   ? "warn" : "danger";
  const tempC = status?.temperature;
  const tempTone =
    tempC == null   ? "info" :
    tempC < 70      ? "ok" :
    tempC < 80      ? "warn" : "danger";
  const wifi = status?.wifi_signal ?? 0;
  const wifiTone = wifi >= 3 ? "ok" : wifi >= 1 ? "warn" : "danger";
  const aiOk = !!status; // proxy for AI cloud reachable

  return (
    <section
      class="card"
      aria-labelledby="qs-title"
      style={{ padding: "var(--s-5)" }}
    >
      <h2
        id="qs-title"
        style={{ margin: "0 0 var(--s-4)", fontSize: "var(--t-lg)" }}
      >
        Status singkat
      </h2>
      <ul
        style={{
          listStyle: "none",
          padding: 0,
          margin: 0,
          display: "grid",
          gap: "var(--s-3)",
          gridTemplateColumns: "repeat(2, 1fr)",
        }}
      >
        <StatRow
          icon="battery"
          label={t("status.battery")}
          value={battery == null ? t("status.battery_unset") : `${battery}%`}
          tone={batteryTone}
        />
        <StatRow
          icon="wifi"
          label={t("status.wifi")}
          value={status?.wifi_ssid || t("status.wifi_no")}
          tone={wifiTone}
        />
        <StatRow
          icon="thermometer"
          label={t("status.temperature")}
          value={tempC == null ? "—" : `${tempC.toFixed(1)}°C`}
          tone={tempTone}
        />
        <StatRow
          icon="cloud"
          label={t("status.cloud_ai")}
          value={aiOk ? "Aktif" : "—"}
          tone={aiOk ? "ok" : "warn"}
        />
      </ul>
    </section>
  );
}

function StatRow({
  icon, label, value, tone,
}: {
  icon: string;
  label: string;
  value: string;
  tone: "ok" | "warn" | "danger" | "info";
}) {
  return (
    <li
      style={{
        display: "flex",
        alignItems: "center",
        gap: "var(--s-3)",
        padding: "var(--s-3)",
        background: "var(--surface-2)",
        borderRadius: "var(--r-md)",
      }}
    >
      <Icon name={icon} size={22} />
      <div style={{ minWidth: 0, flex: 1 }}>
        <div
          style={{
            fontSize: "var(--t-xs)",
            color: "var(--ink-3)",
            textTransform: "uppercase",
            letterSpacing: ".05em",
            fontWeight: 700,
          }}
        >
          {label}
        </div>
        <div
          style={{
            fontSize: "var(--t-md)",
            fontWeight: 600,
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {value}
        </div>
      </div>
      <span class={`badge badge--${tone}`} aria-hidden="true">
        <span class={`dot dot--${tone === "info" ? "ok" : tone}`} />
      </span>
    </li>
  );
}

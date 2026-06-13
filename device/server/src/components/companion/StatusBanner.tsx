import { Icon } from "../atoms/Icon";
import type { DeviceStatus } from "./types";
import { t } from "../../lib/i18n";

export function StatusBanner({
  online,
  status,
}: {
  online: boolean;
  status: DeviceStatus | null;
}) {
  return (
    <div
      class="card"
      role="status"
      aria-live="polite"
      style={{
        padding: "var(--s-5) var(--s-6)",
        display: "flex",
        alignItems: "center",
        gap: "var(--s-5)",
        background: online ? "var(--ok-soft)" : "var(--danger-soft)",
        borderColor: "transparent",
      }}
    >
      <div
        style={{
          width: 56,
          height: 56,
          borderRadius: "50%",
          background: online ? "var(--ok)" : "var(--danger)",
          color: "var(--ink-inverse)",
          display: "grid",
          placeItems: "center",
          flexShrink: 0,
        }}
      >
        <Icon name={online ? "check" : "cross"} size={32} strokeWidth={3} />
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            fontSize: "var(--t-xs)",
            color: online ? "var(--ok)" : "var(--danger)",
            fontWeight: 700,
            letterSpacing: ".06em",
            textTransform: "uppercase",
          }}
        >
          {online ? t("status.device_online") : t("status.device_offline")}
        </div>
        <div
          style={{
            fontSize: "var(--t-xl)",
            fontWeight: 700,
            color: "var(--ink)",
          }}
        >
          AuralAI
        </div>
        <div style={{ fontSize: "var(--t-sm)", color: "var(--ink-2)" }}>
          {status?.wifi_ssid
            ? `${status.wifi_ssid} · WiFi ${status.wifi_signal}/4`
            : online
              ? "Polling…"
              : "Tidak ada koneksi"}
        </div>
      </div>
    </div>
  );
}

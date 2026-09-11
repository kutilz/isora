import { Icon } from "../atoms/Icon";
import type { DeviceStatus } from "./types";
import { t } from "../../lib/i18n";

/**
 * Hard warning while Mode Ambil Data is on: every assistive feature is
 * disabled and the state survives reboots, so the caregiver home must say
 * it loudly and link the one page that can turn it off (/collect).
 */
export function CollectBanner({ status }: { status: DeviceStatus | null }) {
  if (!status?.data_collection_mode) return null;
  const count =
    typeof status.capture_count === "number" ? status.capture_count : null;
  return (
    <div
      class="card"
      role="alert"
      style={{
        marginTop: "var(--s-4)",
        padding: "var(--s-5) var(--s-6)",
        display: "flex",
        alignItems: "center",
        flexWrap: "wrap",
        gap: "var(--s-4)",
        background: "var(--warn-soft)",
        borderColor: "var(--warn)",
      }}
    >
      <div
        style={{
          width: 48,
          height: 48,
          borderRadius: "50%",
          background: "var(--warn)",
          color: "var(--ink-inverse)",
          display: "grid",
          placeItems: "center",
          flexShrink: 0,
        }}
      >
        <Icon name="camera" size={26} />
      </div>
      <div style={{ flex: 1, minWidth: 220 }}>
        <div
          style={{
            fontWeight: 800,
            color: "var(--warn)",
            fontSize: "var(--t-md)",
          }}
        >
          {t("collect.banner_title")}
          {" — "}
          {status.capturing ? t("collect.recording") : t("collect.standby")}
          {count !== null ? ` · ${count} ${t("collect.photos")}` : ""}
        </div>
        <div style={{ color: "var(--ink-2)", fontSize: "var(--t-sm)" }}>
          {t("collect.banner_body")}
        </div>
      </div>
      <a class="btn" href="/collect" style={{ borderColor: "var(--warn)" }}>
        {t("collect.banner_action")}
      </a>
    </div>
  );
}

import { useEffect, useState } from "preact/hooks";
import { StatusBanner } from "./StatusBanner";
import { LiveView } from "./LiveView";
import { ModeSwitcher, type Mode } from "./ModeSwitcher";
import { VolumeControl } from "./VolumeControl";
import { QuickStatus } from "./QuickStatus";
import { ActivityFeed } from "./ActivityFeed";
import { ReportFooter } from "./ReportFooter";
import type { DeviceStatus, HistoryItem } from "./types";
import { usePolling } from "../../lib/polling";
import { apiPost } from "../../lib/api";

/**
 * The dashboard layout shared by `/` and the "Pendamping" view of
 * `/admin`. Pages wrap this with their own header/chrome.
 *
 * Extracts the polling + optimistic-mode + keyboard-shortcut wiring
 * so admin gets the exact same companion experience underneath its
 * extra panels.
 */
export function CompanionDashboard({
  debugOverlay = false,
}: {
  debugOverlay?: boolean;
}) {
  const { data: status, online } = usePolling<DeviceStatus>("/status", 1000);
  const { data: history } = usePolling<{ items: HistoryItem[] }>(
    "/history?date=today",
    5000,
  );

  const [optimisticMode, setOptimisticMode] = useState<Mode | null>(null);
  useEffect(() => {
    if (status && optimisticMode && status.mode === optimisticMode) {
      setOptimisticMode(null);
    }
  }, [status, optimisticMode]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const inField =
        !!target &&
        (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) ||
          target.isContentEditable);
      if (inField) return;
      if (e.key === "1") {
        apiPost("/command", { cmd: "set_mode", mode: "explorer" }).catch(() => {});
        setOptimisticMode("explorer");
      } else if (e.key === "2") {
        apiPost("/command", { cmd: "set_mode", mode: "context" }).catch(() => {});
        setOptimisticMode("context");
      } else if (e.key === "3") {
        apiPost("/command", { cmd: "set_mode", mode: "qris" }).catch(() => {});
        setOptimisticMode("qris");
      } else if (e.key === "?") {
        alert(
          "Pintasan keyboard:\n" +
            "1 / 2 / 3 — ganti mode (Jelajah / Deskripsi / QRIS)\n" +
            "+ / − — ubah volume ±10\n" +
            "Tab — navigasi ke kontrol berikutnya",
        );
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const mode: Mode = optimisticMode ?? status?.mode ?? "explorer";
  const audioMode = status?.audio_mode ?? "both";

  return (
    <div style={{ position: "relative" }}>
      <StatusBanner online={online} status={status} />
      {debugOverlay && <DebugPanel status={status} online={online} />}

      <div
        class="companion-grid"
        style={{
          display: "grid",
          gap: "var(--s-5)",
          gridTemplateColumns: "minmax(0, 1.4fr) minmax(0, 1fr)",
          alignItems: "start",
          marginTop: "var(--s-5)",
        }}
      >
        <div style={{ display: "grid", gap: "var(--s-5)" }}>
          <LiveView status={status} />
          <ActivityFeed items={history?.items ?? []} />
        </div>
        <div style={{ display: "grid", gap: "var(--s-5)" }}>
          <ModeSwitcher active={mode} onOptimistic={setOptimisticMode} />
          <VolumeControl initialVolume={80} initialMode={audioMode} />
          <QuickStatus status={status} />
        </div>
      </div>

      <div style={{ marginTop: "var(--s-5)" }}>
        <ReportFooter />
      </div>

      <style>{`
        @media (max-width: 1100px) {
          .companion-grid { grid-template-columns: 1fr !important; }
        }
      `}</style>
    </div>
  );
}

/** Floating debug strip — shown only when admin enables Debug Overlay. */
function DebugPanel({
  status,
  online,
}: {
  status: DeviceStatus | null;
  online: boolean;
}) {
  const lat = status?.latency || {};
  const cells: [string, string | number | undefined][] = [
    ["online", String(online)],
    ["mode", status?.mode],
    ["fps", typeof lat.fps === "number" ? lat.fps.toFixed(1) : "—"],
    ["cam_ms", lat.camera_ms],
    ["inf_ms", lat.inference_ms],
    ["post_ms", lat.postproc_ms],
    ["total_ms", lat.total_ms],
    ["batt", status?.battery ?? "—"],
    ["wifi", `${status?.wifi_signal ?? 0}/4`],
    ["ssid", status?.wifi_ssid || "—"],
    ["temp", status?.temperature?.toFixed(1) ?? "—"],
    ["audio_mode", status?.audio_mode],
    ["last_cap", (status?.last_caption.text || "—").slice(0, 40)],
  ];
  return (
    <div
      role="status"
      aria-label="Debug overlay"
      style={{
        marginTop: "var(--s-3)",
        padding: "var(--s-3)",
        background: "var(--ink)",
        color: "var(--ink-inverse)",
        borderRadius: "var(--r-md)",
        fontFamily: "var(--font-mono)",
        fontSize: 11,
        display: "flex",
        flexWrap: "wrap",
        gap: "var(--s-3) var(--s-5)",
      }}
    >
      {cells.map(([k, v]) => (
        <span key={k}>
          <span style={{ opacity: 0.6 }}>{k}=</span>
          <span style={{ fontWeight: 700 }}>{String(v ?? "—")}</span>
        </span>
      ))}
    </div>
  );
}

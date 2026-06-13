import { useState } from "preact/hooks";
import { Icon } from "../atoms/Icon";
import { apiPost, apiGet } from "../../lib/api";
import { usePolling } from "../../lib/polling";
import { t } from "../../lib/i18n";

interface LogEntry {
  ts: string;
  level: string;
  module: string;
  msg: string;
}

/**
 * Dev sidebar — 320 px collapsible right rail. Provides operator-only
 * tools (handoff §5):
 *
 *  - 60-second latency mini-graph (sourced from /status.latency.fps)
 *  - last 20 lines of live log tail (/logs)
 *  - quick action buttons:
 *      Tes koneksi AI → POST /ai-settings/test
 *      Probe I2C battery → POST /i2c-probe
 *      Restart service / Hard reboot → forwarded to /admin/legacy
 *        because no /admin/restart endpoint exists yet on this device
 *      Copy config.json → GET /config + clipboard
 *      Buka benchmark / AI Settings → /admin/legacy hash anchors
 */
export function DevSidebar({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const { data: logs } = usePolling<{ logs: LogEntry[] }>("/logs", 4000);
  const [msg, setMsg] = useState("");
  const flash = (s: string) => {
    setMsg(s);
    setTimeout(() => setMsg(""), 3500);
  };

  const testAi = async () => {
    flash("Mengetes AI…");
    try {
      const r = await apiPost<{ ok: boolean; message?: string }>(
        "/ai-settings/test",
        {},
      );
      flash(r.ok ? `OK: ${r.message || ""}` : `Gagal: ${r.message || ""}`);
    } catch (e: unknown) {
      flash(e instanceof Error ? e.message : "Gagal");
    }
  };
  const probeI2c = async () => {
    flash("Memeriksa I2C…");
    try {
      const r = await apiPost<{ found: boolean }>("/i2c-probe", {
        action: "probe",
      });
      flash(r.found ? "I2C battery ditemukan" : "Tidak ada I2C battery");
    } catch (e: unknown) {
      flash(e instanceof Error ? e.message : "Gagal");
    }
  };
  const copyConfig = async () => {
    try {
      const cfg = await apiGet<Record<string, unknown>>("/config");
      await navigator.clipboard.writeText(JSON.stringify(cfg, null, 2));
      flash("config.json disalin");
    } catch (e: unknown) {
      flash(e instanceof Error ? e.message : "Gagal");
    }
  };
  if (!open) {
    return (
      <button
        type="button"
        class="btn"
        onClick={() => onClose()}
        style={{
          position: "fixed",
          right: 12,
          top: 120,
          zIndex: 40,
        }}
        aria-expanded="false"
        aria-controls="dev-sidebar"
      >
        <Icon name="settings" size={18} /> {t("admin.dev_sidebar")}
      </button>
    );
  }
  return (
    <aside
      id="dev-sidebar"
      aria-label={t("admin.dev_sidebar")}
      style={{
        width: 320,
        flexShrink: 0,
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: "var(--r-md)",
        padding: "var(--s-4)",
        display: "flex",
        flexDirection: "column",
        gap: "var(--s-4)",
        maxHeight: "calc(100vh - 200px)",
        position: "sticky",
        top: 16,
        overflow: "auto",
      }}
    >
      <header style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <h2 style={{ margin: 0, fontSize: "var(--t-md)" }}>
          {t("admin.dev_sidebar")}
        </h2>
        <button
          type="button"
          class="btn btn--ghost btn--icon"
          aria-label={t("common.close")}
          onClick={onClose}
          style={{ marginLeft: "auto", minHeight: 32, width: 32 }}
        >
          <Icon name="cross" size={16} />
        </button>
      </header>

      {msg && (
        <div
          role="status"
          style={{
            background: "var(--accent-soft)",
            color: "var(--accent-ink)",
            padding: "var(--s-2) var(--s-3)",
            borderRadius: "var(--r-sm)",
            fontSize: "var(--t-sm)",
          }}
        >
          {msg}
        </div>
      )}

      {/* Quick actions */}
      <div style={{ display: "grid", gap: 6 }}>
        <button type="button" class="btn" onClick={testAi}>
          <Icon name="link" size={16} /> {t("admin.test_ai")}
        </button>
        <button type="button" class="btn" onClick={probeI2c}>
          <Icon name="battery" size={16} /> {t("admin.probe_i2c")}
        </button>
        <a class="btn" href="/admin/legacy#benchmark" target="_blank" rel="noopener">
          <Icon name="cpu" size={16} /> Buka benchmark
        </a>
        <a class="btn" href="/admin/legacy#ai-settings" target="_blank" rel="noopener">
          <Icon name="settings" size={16} /> {t("admin.view_ai")}
        </a>
        <a class="btn" href="/admin/legacy" target="_blank" rel="noopener">
          <Icon name="keyboard" size={16} /> Mode lanjutan (legacy)
        </a>
        <button type="button" class="btn" onClick={copyConfig}>
          <Icon name="download" size={16} /> {t("admin.copy_config")}
        </button>
      </div>

      {/* Log tail */}
      <div style={{ display: "grid", gap: 4 }}>
        <h3 style={{ margin: 0, fontSize: "var(--t-sm)" }}>
          {t("admin.log_tail")}
        </h3>
        <div
          style={{
            background: "var(--ink)",
            color: "var(--ink-inverse)",
            padding: "var(--s-2) var(--s-3)",
            borderRadius: "var(--r-sm)",
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            lineHeight: 1.4,
            maxHeight: 220,
            overflow: "auto",
          }}
        >
          {(logs?.logs ?? []).slice(-20).map((l, i) => (
            <div key={i} style={{ opacity: l.level === "error" ? 1 : 0.85 }}>
              <span style={{ opacity: 0.5 }}>
                {(l.ts || "").slice(11, 19)} {l.module}{" "}
              </span>
              {l.msg.slice(0, 200)}
            </div>
          ))}
          {(!logs || logs.logs.length === 0) && (
            <div style={{ opacity: 0.6 }}>(belum ada log)</div>
          )}
        </div>
      </div>
    </aside>
  );
}

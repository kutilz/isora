import { render } from "preact";
import { useState } from "preact/hooks";
import { A11yBar } from "../components/atoms/A11yBar";
import { SkipLink } from "../components/atoms/SkipLink";
import { Icon } from "../components/atoms/Icon";
import { AdminRibbon } from "../components/admin/AdminRibbon";
import { DevSidebar } from "../components/admin/DevSidebar";
import { CompanionDashboard } from "../components/companion/CompanionDashboard";
import { ensureToken } from "../lib/api";
import { t } from "../lib/i18n";
import "../styles/global.css";

type View = "companion" | "setup" | "logs" | "benchmark" | "ai" | "legacy";

const VIEWS: { id: View; labelKey: string; href?: string }[] = [
  { id: "companion", labelKey: "admin.view_companion" },
  { id: "setup",     labelKey: "admin.view_setup",     href: "/setup" },
  { id: "logs",      labelKey: "admin.view_logs",      href: "/admin/legacy#logs" },
  { id: "benchmark", labelKey: "admin.view_benchmark", href: "/admin/legacy#benchmark" },
  { id: "ai",        labelKey: "admin.view_ai",        href: "/admin/legacy#ai-settings" },
  { id: "legacy",    labelKey: "Admin legacy" as never, href: "/admin/legacy" },
];

function AdminApp() {
  const [debugOverlay, setDebugOverlay] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);

  const handleViewChange = (e: Event) => {
    const v = (e.currentTarget as HTMLSelectElement).value as View;
    if (v === "companion") return;
    const target = VIEWS.find((x) => x.id === v)?.href;
    if (target) window.location.href = target;
  };

  return (
    <div class="app-shell">
      <AdminRibbon />
      <SkipLink />
      <A11yBar />

      <header class="app-header">
        <div class="app-header__logo">
          <span
            style={{
              width: 36,
              height: 36,
              borderRadius: 8,
              background: "var(--accent)",
              color: "var(--ink-inverse)",
              display: "grid",
              placeItems: "center",
            }}
          >
            <Icon name="glasses" size={20} />
          </span>
          <span>
            <div style={{ fontWeight: 700 }}>AuralAI</div>
            <div style={{ fontSize: "var(--t-xs)", color: "var(--ink-3)" }}>
              Admin
            </div>
          </span>
        </div>

        <label
          style={{
            marginLeft: "var(--s-6)",
            display: "inline-flex",
            alignItems: "center",
            gap: 8,
            fontSize: "var(--t-sm)",
            fontWeight: 600,
          }}
        >
          {t("admin.view_as")}:
          <select
            value="companion"
            onChange={handleViewChange}
            style={{
              font: "inherit",
              padding: "8px 12px",
              borderRadius: "var(--r-md)",
              border: "2px solid var(--border-strong)",
              background: "var(--surface)",
              color: "var(--ink)",
              minHeight: 40,
            }}
          >
            {VIEWS.map((v) => (
              <option key={v.id} value={v.id}>
                {v.id === "companion" ? t("admin.view_companion") : t(v.labelKey)}
              </option>
            ))}
          </select>
        </label>

        <label
          style={{
            marginLeft: "var(--s-5)",
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            fontSize: "var(--t-sm)",
            fontWeight: 600,
          }}
        >
          <input
            type="checkbox"
            checked={debugOverlay}
            onChange={(e) =>
              setDebugOverlay((e.currentTarget as HTMLInputElement).checked)
            }
            style={{ accentColor: "var(--accent)" }}
          />
          {t("admin.debug_overlay")}
        </label>

        <span class="app-header__spacer" />

        <a href="/" class="btn btn--ghost" style={{ minHeight: 40 }}>
          {t("nav.companion")}
        </a>
        <a href="/admin/legacy" class="btn btn--ghost" style={{ minHeight: 40 }}>
          Legacy
        </a>
      </header>

      <main
        id="main"
        tabIndex={-1}
        style={{
          padding: "var(--s-5)",
          maxWidth: 1600,
          margin: "0 auto",
          width: "100%",
          display: "flex",
          gap: "var(--s-5)",
          alignItems: "flex-start",
        }}
      >
        <div style={{ flex: 1, minWidth: 0, display: "grid", gap: "var(--s-5)" }}>
          <CompanionDashboard debugOverlay={debugOverlay} />
        </div>
        <DevSidebar open={sidebarOpen} onClose={() => setSidebarOpen((v) => !v)} />
      </main>
    </div>
  );
}

ensureToken().finally(() => {
  render(<AdminApp />, document.getElementById("root")!);
});

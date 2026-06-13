import { render } from "preact";
import { A11yBar } from "../components/atoms/A11yBar";
import { SkipLink } from "../components/atoms/SkipLink";
import { Icon } from "../components/atoms/Icon";
import { CompanionDashboard } from "../components/companion/CompanionDashboard";
import { ensureToken } from "../lib/api";
import { t } from "../lib/i18n";
import "../styles/global.css";

function CompanionApp() {
  return (
    <div class="app-shell">
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
              {t("nav.companion")}
            </div>
          </span>
        </div>
        <span class="app-header__spacer" />
        <nav aria-label="Menu utama" style={{ display: "flex", gap: 4 }}>
          <a href="/setup" class="btn btn--ghost" style={{ minHeight: 40 }}>
            {t("nav.setup")}
          </a>
          <a href="/guide" class="btn btn--ghost" style={{ minHeight: 40 }}>
            {t("nav.guide")}
          </a>
          <a href="/admin" class="btn btn--ghost" style={{ minHeight: 40 }}>
            {t("nav.admin")}
          </a>
        </nav>
      </header>

      <main
        id="main"
        tabIndex={-1}
        style={{
          padding: "var(--s-5)",
          display: "grid",
          gap: "var(--s-5)",
          maxWidth: 1400,
          margin: "0 auto",
          width: "100%",
        }}
      >
        <CompanionDashboard />

        <footer
          style={{
            textAlign: "center",
            color: "var(--ink-3)",
            fontSize: "var(--t-xs)",
            padding: "var(--s-4) 0 var(--s-6)",
          }}
        >
          AuralAI · Sesuai WCAG 2.1 AA ·{" "}
          <a href="/admin" style={{ color: "var(--ink-3)" }}>
            {t("nav.admin")}
          </a>
        </footer>
      </main>
    </div>
  );
}

ensureToken().finally(() => {
  render(<CompanionApp />, document.getElementById("root")!);
});

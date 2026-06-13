import { t } from "@/lib/i18n";
import Logo from "./Logo";

export default function Footer() {
  return (
    <footer className="site-footer">
      <div className="container">
        <p style={{ margin: 0, display: "flex", alignItems: "center", gap: 10, fontWeight: 700, color: "var(--ink-2)" }}>
          <Logo size={22} />
          {t.footer.made}
        </p>
        <p style={{ margin: "8px 0 0" }}>{t.footer.offline}</p>
      </div>
    </footer>
  );
}

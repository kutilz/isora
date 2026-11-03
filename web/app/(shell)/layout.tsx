import { t } from "@/lib/i18n";

/**
 * App-shell chrome. No marketing nav or footer: once I-Sora is installed to the
 * home screen these pages ARE the app, and each screen carries its own AppBar.
 */
export default function ShellLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="app-shell">
      <a href="#main" className="skip-link">
        Lewati ke konten utama
      </a>
      <main id="main">{children}</main>
      <p className="wcag-note">{t.footer.wcag}</p>
    </div>
  );
}

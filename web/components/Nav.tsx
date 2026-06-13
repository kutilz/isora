import Link from "next/link";
import { t } from "@/lib/i18n";
import Logo from "./Logo";

export default function Nav() {
  return (
    <header className="site-header">
      <div className="container bar">
        <Link href="/" className="brand" aria-label={`${t.app} — beranda`}>
          <Logo size={28} />
          <span className="brand-wm">
            <span>I</span>-Sora
          </span>
        </Link>
        <nav className="site-nav" aria-label="Navigasi utama">
          <Link href="/pair">{t.nav.pair}</Link>
          <Link href="/docs">{t.nav.docs}</Link>
          <Link href="/preview">{t.nav.preview}</Link>
          <Link href="/dashboard">{t.nav.dashboard}</Link>
        </nav>
      </div>
    </header>
  );
}

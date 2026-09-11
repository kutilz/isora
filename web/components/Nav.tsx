"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { t } from "@/lib/i18n";
import Logo from "./Logo";

const LINKS = [
  { href: "/pair", label: t.nav.pair },
  { href: "/docs", label: t.nav.docs },
  { href: "/preview", label: t.nav.preview },
  { href: "/dashboard", label: t.nav.dashboard },
];

export default function Nav() {
  const pathname = usePathname();
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
          {LINKS.map((l) => {
            const active = pathname === l.href || pathname.startsWith(`${l.href}/`);
            return (
              <Link
                key={l.href}
                href={l.href}
                aria-current={active ? "page" : undefined}
              >
                {l.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}

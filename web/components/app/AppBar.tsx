"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import type { ReactNode } from "react";

/**
 * App-shell top bar. `back` renders a real link (so it works with a long-press
 * "open in new tab" and with no JS) but navigates via history when there is one
 * — that keeps the standalone PWA's back stack feeling native.
 */
export default function AppBar({
  title,
  back,
  trailing,
}: {
  title: string;
  /** Destination to fall back to when there's no history to pop. */
  back?: string;
  trailing?: ReactNode;
}) {
  const router = useRouter();

  return (
    <header className="app-bar">
      {back && (
        <Link
          href={back}
          className="app-bar__back"
          aria-label="Kembali"
          onClick={(e) => {
            if (window.history.length > 1) {
              e.preventDefault();
              router.back();
            }
          }}
        >
          <span aria-hidden="true">‹</span>
        </Link>
      )}
      <h1>{title}</h1>
      {trailing && <div className="app-bar__trail">{trailing}</div>}
    </header>
  );
}

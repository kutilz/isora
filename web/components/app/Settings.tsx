import Link from "next/link";
import type { ReactNode } from "react";

/**
 * Grouped-list primitives for the app shell — the phone-settings idiom:
 * a small uppercase caption, then a card of full-width rows.
 *
 * Every row is ONE control with its label and its value together, so a screen
 * reader announces "Layanan AI, OpenAI, tombol" in a single stop instead of
 * making the user hunt for the value in a separate node.
 */

export function SettingsGroup({
  title,
  note,
  children,
}: {
  title?: string;
  note?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="sgroup" aria-label={title}>
      {title && <h2 className="sgroup__title">{title}</h2>}
      <div className="sgroup__list">{children}</div>
      {note && <p className="sgroup__note">{note}</p>}
    </section>
  );
}

type RowContent = {
  label: ReactNode;
  sub?: ReactNode;
  value?: ReactNode;
  /** Leading status dot / icon. */
  lead?: ReactNode;
};

function Inner({ label, sub, value, lead, chevron }: RowContent & { chevron?: boolean }) {
  return (
    <>
      {lead}
      <span className="srow__main">
        <span className="srow__label">{label}</span>
        {sub && <span className="srow__sub">{sub}</span>}
      </span>
      {value !== undefined && <span className="srow__value">{value}</span>}
      {chevron && (
        <span className="srow__chev" aria-hidden="true">
          ›
        </span>
      )}
    </>
  );
}

/** Static row — information, not a control. */
export function SettingsItem(props: RowContent) {
  return (
    <div className="srow">
      <Inner {...props} />
    </div>
  );
}

/** Navigational row. `external` opens the device's own LAN page in a new tab. */
export function SettingsLink({
  href,
  external = false,
  ...rest
}: RowContent & { href: string; external?: boolean }) {
  if (external) {
    return (
      <a className="srow" href={href} target="_blank" rel="noreferrer">
        <Inner {...rest} chevron />
      </a>
    );
  }
  return (
    <Link className="srow" href={href}>
      <Inner {...rest} chevron />
    </Link>
  );
}

/** Action row. */
export function SettingsButton({
  onClick,
  danger = false,
  disabled = false,
  ...rest
}: RowContent & { onClick: () => void; danger?: boolean; disabled?: boolean }) {
  return (
    <button
      type="button"
      className={`srow${danger ? " srow--danger" : ""}`}
      onClick={onClick}
      disabled={disabled}
    >
      <Inner {...rest} chevron={!danger} />
    </button>
  );
}

/** Row that holds a form control (input/select) instead of a value. */
export function SettingsField({ children }: { children: ReactNode }) {
  return <div className="srow srow--field">{children}</div>;
}

/** Connection pill used in headers and device rows. */
export function StatusPill({ online }: { online: boolean }) {
  return (
    <span className={`pill ${online ? "pill--ok" : "pill--off"}`}>
      <span className={`dot ${online ? "dot--ok" : ""}`} aria-hidden="true" style={{ width: 8, height: 8 }} />
      {online ? "Terhubung" : "Terputus"}
    </span>
  );
}

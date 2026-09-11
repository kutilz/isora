import type { CSSProperties, ReactNode } from "react";

type Kind = "ok" | "err" | "info" | "warn";

/**
 * Status/alert box that screen readers actually announce.
 * Errors use role="alert" (assertive); everything else role="status" (polite).
 * Pass `alert` to force assertive announcement (e.g. "assistive features off").
 */
export default function Notice({
  kind = "info",
  alert = false,
  children,
  style,
}: {
  kind?: Kind;
  alert?: boolean;
  children: ReactNode;
  style?: CSSProperties;
}) {
  return (
    <div
      className={`notice notice--${kind}`}
      role={kind === "err" || alert ? "alert" : "status"}
      style={style}
    >
      {children}
    </div>
  );
}

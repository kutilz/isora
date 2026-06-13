/**
 * Vector icon set — ported from designs/icons.jsx.
 * Currents `currentColor`, scales via the `size` prop. No emoji ever.
 */

import type { JSX } from "preact";

const ICONS: Record<string, string> = {
  // status & system
  check:     "M5 13l4 4L19 7",
  cross:     "M6 6l12 12M6 18L18 6",
  warning:   "M12 3l10 18H2L12 3zm0 6v5m0 3v.5",
  info:      "M12 8h.01M11 12h1v5h1",
  battery:   "M3 8h14v8H3zM17 10h2v4h-2",
  wifi:      "M5 12a10 10 0 0114 0M8 15a6 6 0 018 0M12 18h.01",
  wifiOff:   "M5 12a10 10 0 0114 0M2 2l20 20M12 18h.01",
  signal:    "M3 17v2M8 13v6M13 9v10M18 5v14",

  // device
  camera:    "M4 7h3l2-2h6l2 2h3v12H4V7zM12 11a4 4 0 100 8 4 4 0 000-8z",
  glasses:   "M2 12h2m16 0h2M6 12a4 4 0 108 0 4 4 0 00-8 0zm6 0a4 4 0 108 0 4 4 0 00-8 0z",
  speaker:   "M4 9v6h4l5 4V5L8 9H4zM16 9c1.5 1 1.5 5 0 6M19 6c3 3 3 9 0 12",
  speakerOff:"M4 9v6h4l5 4V5L8 9H4zM17 9l5 5m0-5l-5 5",
  mic:       "M12 3a3 3 0 00-3 3v6a3 3 0 006 0V6a3 3 0 00-3-3zM6 11v1a6 6 0 0012 0v-1M12 18v3",

  // modes
  explore:   "M12 2a10 10 0 100 20 10 10 0 000-20zM12 6l2 6 6 2-6 2-2 6-2-6-6-2 6-2 2-6z",
  scene:     "M3 5h18v14H3zM3 15l5-5 4 4 3-3 6 6",
  qris:      "M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h3v3h-3zM18 14h3M14 18v3M18 21h3v-3",

  // actions
  play:      "M6 4l14 8-14 8z",
  pause:     "M6 4h4v16H6zM14 4h4v16h-4z",
  refresh:   "M21 12a9 9 0 11-3-6.7L21 8M21 3v5h-5",
  settings:  "M12 8a4 4 0 100 8 4 4 0 000-8zM19 12a7 7 0 00-.1-1.2l2.1-1.6-2-3.4-2.5.9a7 7 0 00-2-1.2L14 3h-4l-.5 2.5a7 7 0 00-2 1.2l-2.5-.9-2 3.4 2.1 1.6A7 7 0 005 12c0 .4 0 .8.1 1.2l-2.1 1.6 2 3.4 2.5-.9c.6.5 1.3.9 2 1.2L10 21h4l.5-2.5c.7-.3 1.4-.7 2-1.2l2.5.9 2-3.4-2.1-1.6c.1-.4.1-.8.1-1.2z",
  bell:      "M6 17h12l-1.5-2V10a4.5 4.5 0 00-9 0v5L6 17zM10 21h4",
  bellOff:   "M6 17h12l-1.5-2V10a4.5 4.5 0 00-1-2.8M3 3l18 18",
  download:  "M12 4v12m0 0l-4-4m4 4l4-4M4 20h16",
  flag:      "M5 21V4l12 4-12 4",
  history:   "M3 12a9 9 0 109-9 9 9 0 00-8 5M3 3v5h5M12 8v4l3 2",
  search:    "M11 4a7 7 0 100 14 7 7 0 000-14zM16 16l5 5",
  user:      "M12 12a4 4 0 100-8 4 4 0 000 8zM4 21a8 8 0 0116 0",
  caret:     "M6 9l6 6 6-6",
  arrowRight:"M5 12h14m0 0l-5-5m5 5l-5 5",
  arrowLeft: "M19 12H5m0 0l5-5m-5 5l5 5",
  power:     "M12 3v9M5.6 7.6a9 9 0 1012.8 0",
  link:      "M10 14a4 4 0 005.7 0l3-3a4 4 0 00-5.7-5.7l-1 1M14 10a4 4 0 00-5.7 0l-3 3a4 4 0 005.7 5.7l1-1",
  plus:      "M12 5v14M5 12h14",
  minus:     "M5 12h14",
  text:      "M4 6h16M4 12h10M4 18h16",
  contrast:  "M12 3a9 9 0 100 18V3z M12 3a9 9 0 010 18",
  keyboard:  "M3 7h18v10H3zM7 11h.01M11 11h.01M15 11h.01M7 14h10",
  qrCode:    "M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14v7M21 14h-3v3h3M17 17v4",
  thermometer:"M14 14V5a2 2 0 10-4 0v9a4 4 0 104 0z",
  cpu:       "M4 7h16v10H4zM8 4v3M12 4v3M16 4v3M8 17v3M12 17v3M16 17v3M4 11h-2M4 13h-2M22 11h-2M22 13h-2M9 9h6v6H9z",
  cloud:     "M7 18a4 4 0 010-8 5 5 0 019.6-1.4A4 4 0 0117 18H7z",
};

export type IconName = keyof typeof ICONS | string;

export interface IconProps {
  name: IconName;
  size?: number;
  strokeWidth?: number;
  fill?: "none" | "currentColor";
  label?: string;
  className?: string;
  style?: JSX.CSSProperties;
}

export function Icon({
  name,
  size = 20,
  strokeWidth = 2,
  fill,
  label,
  className,
  style,
}: IconProps): JSX.Element {
  const d = ICONS[name] || "";
  const filled = fill === "currentColor";
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill={filled ? "currentColor" : "none"}
      stroke={filled ? "none" : "currentColor"}
      stroke-width={strokeWidth}
      stroke-linecap="round"
      stroke-linejoin="round"
      role={label ? "img" : "presentation"}
      aria-label={label}
      aria-hidden={label ? undefined : "true"}
      className={className}
      style={{ flexShrink: 0, ...style }}
    >
      <path d={d} />
    </svg>
  );
}

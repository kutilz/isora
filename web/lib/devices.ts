/**
 * Shared device-row shape and the small derivations every app screen needs.
 * Kept out of the components so the device list and the device settings screen
 * can never disagree about what "Terhubung" means.
 */

export type DeviceStatus = {
  mode?: string;
  wifi?: string;
  battery?: number;
  online?: boolean;
  data_collection_mode?: boolean;
  capturing?: boolean;
  capture_count?: number;
  local_url?: string;
  local_ip_url?: string;
  /** Device-reported: has first-time setup been finished on the device itself? */
  setup_completed?: boolean;
  /** Device-reported: the selected AI provider actually has a key. */
  ai_ready?: boolean;
  /** Online navigation (explorer + ACTION) is switched on right now. */
  scan_active?: boolean;
  /** Seconds between online-navigation photos (device clamps to 3-60). */
  scan_interval_s?: number;
};

export type DeviceRow = {
  id: string;
  name: string | null;
  fw_version: string | null;
  status: DeviceStatus | null;
  last_seen: string | null;
  /** The browser reached the relay from the same public IP as the device. */
  same_network?: boolean;
  /** Only present on the detail endpoint — needed for client-side E2E. */
  pubkey?: string | null;
};

/** Device heartbeats every 20 s; allow a few misses before calling it offline. */
export const ONLINE_WINDOW_MS = 90_000;

export function isOnline(d: Pick<DeviceRow, "last_seen">): boolean {
  if (!d.last_seen) return false;
  return Date.now() - new Date(d.last_seen).getTime() < ONLINE_WINDOW_MS;
}

export function lastSeenText(lastSeen: string): string {
  const mins = Math.max(1, Math.round((Date.now() - new Date(lastSeen).getTime()) / 60_000));
  if (mins < 60) return `${mins} menit lalu`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours} jam lalu`;
  return `${Math.round(hours / 24)} hari lalu`;
}

export function deviceLabel(d: Pick<DeviceRow, "id" | "name">): string {
  return d.name || `I-Sora ${d.id.slice(-4)}`;
}

function httpUrl(u: unknown): string | null {
  return typeof u === "string" && u.startsWith("http") ? u.replace(/\/$/, "") : null;
}

/**
 * The device's LAN entry point, as reported in its heartbeat. Only usable from
 * the same WiFi — and only ever as a link: a page served over HTTPS cannot
 * fetch a plain-HTTP LAN address (mixed content), so we never probe it.
 *
 * The IP form is preferred over the `.local` name because Chrome on Android
 * does not resolve mDNS names at all; the name is kept as a fallback (and shown
 * separately) since it survives a DHCP lease change.
 */
export function localUrl(d: Pick<DeviceRow, "status">): string | null {
  return httpUrl(d.status?.local_ip_url) ?? httpUrl(d.status?.local_url);
}

/** The stable `http://<name>.local:<port>` address, for display. */
export function mdnsUrl(d: Pick<DeviceRow, "status">): string | null {
  return httpUrl(d.status?.local_url);
}

/**
 * "This device is paired but its first-time setup was never finished."
 *
 * Only the device can answer this, so it rides along in the heartbeat. Firmware
 * that predates the flag leaves it undefined, which we read as "set up" — a
 * false nag is worse than silence when we genuinely do not know.
 *
 * It exists because pairing completes on the DEVICE the moment the button is
 * pressed. If the phone then closes, reloads or wanders off the setup screen,
 * nothing on the relay remembers that a half-finished setup is owed — and the
 * person is left holding a linked device with no visible way onward.
 */
export function needsSetup(d: Pick<DeviceRow, "status">): boolean {
  return d.status?.setup_completed === false;
}

/** One-line summary for the device row in the list. */
export function deviceSummary(d: DeviceRow): string {
  if (!isOnline(d)) {
    const last = d.last_seen ? `Terputus · terakhir ${lastSeenText(d.last_seen)}` : "Belum pernah terhubung";
    return needsSetup(d) ? `${last} · perlu disiapkan` : last;
  }
  if (needsSetup(d)) return "Terhubung · perlu disiapkan";
  const bits: string[] = [];
  if (d.status?.mode) bits.push(String(d.status.mode));
  if (typeof d.status?.battery === "number") bits.push(`baterai ${d.status.battery}%`);
  if (d.same_network) bits.push("WiFi yang sama");
  return bits.length ? `Terhubung · ${bits.join(" · ")}` : "Terhubung";
}

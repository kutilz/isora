/**
 * Simulator constants — a faithful copy of the device's numbers.
 *
 * Every value here has a counterpart in the firmware, noted per block. The
 * point of the simulator is that someone without hardware hears *what the
 * device would say*, so these must not be "close enough" — if you tune the
 * device, tune these too.
 *
 * Sources: device/config.py (NAV_OBJECTS, conf_threshold, danger_area_threshold),
 * device/utils/distance.py, device/utils/announce_policy.py,
 * device/core/audio_manager.py (_LABEL_ID / _POS_KEY / _POS_PHRASE).
 */

/** COCO label → Indonesian spoken id. Mirrors config.NAV_OBJECTS. */
export const NAV_OBJECTS: Record<string, string> = {
  person: "orang",
  motorcycle: "motor",
  car: "mobil",
  bicycle: "sepeda",
  bus: "bus",
  truck: "truk",
  dog: "anjing",
  cat: "kucing",
  chair: "kursi",
  bottle: "botol",
  handbag: "tas",
  backpack: "ransel",
};

export const RELEVANT_LABELS = new Set(Object.keys(NAV_OBJECTS));

/** Indonesian 3×3 grid cell → English position key. Mirrors _POS_KEY. */
export const POS_KEY: Record<string, string> = {
  tengah: "center",
  kiri: "left",
  kanan: "right",
  atas: "top",
  bawah: "bottom",
  "kiri-atas": "top_left",
  "kanan-atas": "top_right",
  "kiri-bawah": "bottom_left",
  "kanan-bawah": "bottom_right",
};

/** Position key → spoken Indonesian phrase. Mirrors _POS_PHRASE. */
export const POS_PHRASE: Record<string, string> = {
  left: "di sebelah kiri",
  right: "di sebelah kanan",
  center: "di depan",
  top: "di atas",
  bottom: "di bawah",
  top_left: "di kiri atas",
  top_right: "di kanan atas",
  bottom_left: "di kiri bawah",
  bottom_right: "di kanan bawah",
};

/** Per-class area_ratio at which an object becomes "near". distance.py. */
export const NEAR_AREA_THRESHOLDS: Record<string, number> = {
  bottle: 0.04,
  handbag: 0.05,
  backpack: 0.06,
  cat: 0.06,
  dog: 0.1,
  chair: 0.12,
  person: 0.15,
  bicycle: 0.16,
  motorcycle: 0.18,
  car: 0.3,
  truck: 0.38,
  bus: 0.4,
};

export const DEFAULT_NEAR_AREA = 0.15;
export const GROUND_NUDGE_MAX = 0.25;
export const GROUND_NUDGE_START = 0.55;
export const HYSTERESIS_MARGIN = 0.1;

/** config.py: an object filling this much of the frame is flagged urgent. */
export const DANGER_AREA_THRESHOLD = 0.15;

/** config.py: minimum detector confidence before a box counts at all. */
export const CONF_THRESHOLD = 0.6;

/** announce_policy._DEFAULTS. */
export const ANNOUNCE_COOLDOWN_S = 1.5;
export const ANNOUNCE_DANGER_REMIND_S = 3.0;
export const ANNOUNCE_MAX_PER_TICK = 2;

/**
 * How often the simulator runs inference. The device's AI loop is frame-paced
 * on its own hardware; on a phone we throttle so the browser stays responsive
 * and the phone stays cool.
 */
export const INFERENCE_INTERVAL_MS = 350;

/** Spoken caption for one announcement — the exact string the device speaks. */
export function caption(label: string, cell: string, tier: string): string {
  const posKey = POS_KEY[cell] ?? cell;
  const objId = NAV_OBJECTS[label] ?? label;
  const phrase = POS_PHRASE[posKey] ?? cell;
  const suffix = tier === "near" ? " dekat" : "";
  return `${objId} ${phrase}${suffix}`.trim();
}

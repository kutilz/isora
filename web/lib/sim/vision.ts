/**
 * Geometry → meaning. Direct ports of device/utils/logger.position_from_bbox
 * and device/utils/distance.band, kept pure so they can be reasoned about (and
 * diffed against the Python) without a camera.
 */

import {
  DEFAULT_NEAR_AREA,
  GROUND_NUDGE_MAX,
  GROUND_NUDGE_START,
  HYSTERESIS_MARGIN,
  NEAR_AREA_THRESHOLDS,
} from "./constants";

export type Tier = "near" | "far";

/** Map a box centre to the Indonesian 3×3 grid cell ("kiri", "kanan-bawah", …). */
export function positionFromBbox(
  x: number,
  y: number,
  w: number,
  h: number,
  frameW: number,
  frameH: number
): string {
  const cx = x + w / 2;
  const cy = y + h / 2;
  const col = Math.min(Math.floor((cx / frameW) * 3), 2);
  const row = Math.min(Math.floor((cy / frameH) * 3), 2);
  const colN = ["kiri", "tengah", "kanan"][col];
  const rowN = ["atas", "tengah", "bawah"][row];
  if (rowN === "tengah") return colN;
  if (colN === "tengah") return rowN;
  return `${colN}-${rowN}`;
}

function thresholdFor(label: string): number {
  return NEAR_AREA_THRESHOLDS[label] ?? DEFAULT_NEAR_AREA;
}

/**
 * How much of the near-cutoff to shave off because the box sits low in frame
 * (a monocular ground-contact cue). 0 when the base is high up, ramping to
 * GROUND_NUDGE_MAX at the very bottom.
 */
function groundDiscount(bboxBottomNorm: number): number {
  if (bboxBottomNorm <= GROUND_NUDGE_START || GROUND_NUDGE_MAX <= 0) return 0;
  const span = 1 - GROUND_NUDGE_START;
  if (span <= 0) return GROUND_NUDGE_MAX;
  const frac = Math.min(Math.max((bboxBottomNorm - GROUND_NUDGE_START) / span, 0), 1);
  return GROUND_NUDGE_MAX * frac;
}

/**
 * Coarse distance tier for one detection.
 *
 * `prevTier` drives the hysteresis band: entering "near" needs the area to
 * clear the cutoff by +margin, dropping back to "far" needs it to fall below
 * by −margin. Without that, an object hovering on the boundary would flip every
 * frame and each flip is a spoken "dekat".
 */
export function distanceBand(
  label: string,
  areaRatio: number,
  bboxBottomNorm: number,
  prevTier?: Tier | null
): Tier {
  if (areaRatio <= 0) return "far";

  const effective = thresholdFor(label) * (1 - groundDiscount(bboxBottomNorm));
  const enter = effective * (1 + HYSTERESIS_MARGIN);
  const exit = effective * (1 - HYSTERESIS_MARGIN);

  if (!prevTier) return areaRatio >= effective ? "near" : "far";
  if (prevTier === "near") return areaRatio < exit ? "far" : "near";
  return areaRatio > enter ? "near" : "far";
}

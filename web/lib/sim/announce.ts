/**
 * The nav-speech gate — a port of device/utils/announce_policy.decide.
 *
 * This is the part that makes I-Sora bearable to wear: it speaks on CHANGE
 * (new object, moved grid cell, crossed the near/far line) and keeps a hazard
 * audible on a timer, instead of narrating every frame. Ported verbatim so the
 * simulator is quiet in exactly the places the device is quiet.
 *
 * State lives with the caller; decide() returns the replacement. State is built
 * only from labels present this frame, so a vanished object prunes itself.
 */

import {
  ANNOUNCE_COOLDOWN_S,
  ANNOUNCE_DANGER_REMIND_S,
  ANNOUNCE_MAX_PER_TICK,
} from "./constants";
import type { Tier } from "./vision";

export type Detection = {
  label: string;
  confidence: number;
  /** Indonesian grid cell from positionFromBbox. */
  position: string;
  tier: Tier;
  is_danger: boolean;
  areaRatio: number;
  bbox: { x: number; y: number; w: number; h: number };
};

export type AnnounceState = Record<
  string,
  { cell: string; tier: Tier; danger: boolean; last: number }
>;

export type Announcement = {
  label: string;
  position: string;
  tier: Tier;
  is_danger: boolean;
};

/** Urgent = explicitly flagged, or simply near. Mirrors policy.is_danger. */
export function isDanger(d: Pick<Detection, "is_danger" | "tier">): boolean {
  return !!d.is_danger || d.tier === "near";
}

/**
 * @param now seconds (monotonic-ish, e.g. performance.now() / 1000)
 * @param force on-demand readout: bypasses the cooldown and the per-tick cap
 */
export function decide(
  state: AnnounceState,
  detections: Detection[],
  now: number,
  force = false
): { announcements: Announcement[]; state: AnnounceState } {
  // Urgent first, then by confidence. Stable for ties.
  const ranked = [...detections].sort((a, b) => {
    const da = isDanger(a) ? 1 : 0;
    const db = isDanger(b) ? 1 : 0;
    if (da !== db) return db - da;
    return (b.confidence ?? 0) - (a.confidence ?? 0);
  });

  const next: AnnounceState = {};
  const announcements: Announcement[] = [];
  let spoken = 0;

  for (const det of ranked) {
    const label = det.label;
    // Ignore unlabeled boxes; keep only the best (first) box per label.
    if (!label || label in next) continue;

    const cell = det.position ?? "";
    const tier = det.tier ?? "far";
    const danger = isDanger(det);
    const prev = state[label];
    let last = prev ? prev.last : 0;

    let wanted: boolean;
    if (force) wanted = true;
    else if (!prev) wanted = true; // new object
    else if (cell !== prev.cell || tier !== prev.tier) wanted = true; // moved
    else if (danger && now - last >= ANNOUNCE_DANGER_REMIND_S) wanted = true; // hazard
    else wanted = false; // unchanged & calm

    let speak = wanted;
    if (speak && !force) {
      if (prev && now - last < ANNOUNCE_COOLDOWN_S) speak = false;
      else if (spoken >= ANNOUNCE_MAX_PER_TICK) speak = false;
    }

    if (speak) {
      last = now;
      announcements.push({ label, position: cell, tier, is_danger: danger });
      spoken += 1;
      next[label] = { cell, tier, danger, last };
    } else if (wanted) {
      // Earned a word but suppressed by the cooldown/cap: keep the PRIOR
      // announced state, otherwise the change is lost forever and an obstacle
      // that moved into the path would read as "unchanged" from now on.
      if (prev) next[label] = { ...prev };
      // A brand-new object stays unrecorded so it is retried next frame.
    } else {
      // Unchanged & calm: record current state, carrying `last` from prev.
      next[label] = { cell, tier, danger, last };
    }
  }

  return { announcements, state: next };
}

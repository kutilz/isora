"use client";

/**
 * Object detection for the simulator.
 *
 * The device runs YOLO11n on its NPU; a phone browser can't, so we use
 * COCO-SSD (lite MobileNet v2) via TensorFlow.js. Different network, same
 * label space — which is what matters, because everything downstream keys off
 * the COCO class name (see constants.NAV_OBJECTS).
 *
 * The weights come from Google's CDN on first run and are then held by the
 * service worker's "isora-models" cache, so later runs work with no internet.
 */

import { CONF_THRESHOLD, DANGER_AREA_THRESHOLD, RELEVANT_LABELS } from "./constants";
import type { Detection } from "./announce";
import { distanceBand, positionFromBbox, type Tier } from "./vision";

/** A stalled download must end in a retry button, not an endless "memuat". */
const MODEL_TIMEOUT_MS = 90_000;

export type CocoModel = {
  detect: (
    input: HTMLVideoElement | HTMLCanvasElement,
    maxBoxes?: number,
    minScore?: number
  ) => Promise<{ bbox: [number, number, number, number]; class: string; score: number }[]>;
};

let modelPromise: Promise<CocoModel> | null = null;

/** Loads (and caches) the detector. Safe to call repeatedly. */
export function loadDetector(): Promise<CocoModel> {
  if (!modelPromise) {
    const load = (async () => {
      const tf = await import("@tensorflow/tfjs");
      await tf.ready();
      const cocoSsd = await import("@tensorflow-models/coco-ssd");
      // lite_mobilenet_v2 is the small one — the difference matters on a phone.
      return (await cocoSsd.load({ base: "lite_mobilenet_v2" })) as unknown as CocoModel;
    })();
    const timeout = new Promise<never>((_, reject) => {
      window.setTimeout(() => reject(new Error("model load timed out")), MODEL_TIMEOUT_MS);
    });
    modelPromise = Promise.race([load, timeout]).catch((e) => {
      modelPromise = null; // let the user retry after a failed download
      throw e;
    });
  }
  return modelPromise;
}

/**
 * Run one frame and shape the result exactly like the device's AI loop does
 * (device/core/ai_engine.py): filter to the nav object set, map the box centre
 * to a grid cell, and derive the distance tier with per-label hysteresis.
 *
 * `prevTiers` is the caller-held hysteresis memory; it is mutated in place and
 * pruned to the labels still in view, mirroring `self._prev_tiers`.
 */
export async function detectFrame(
  model: CocoModel,
  source: HTMLVideoElement | HTMLCanvasElement,
  frameW: number,
  frameH: number,
  prevTiers: Map<string, Tier>
): Promise<Detection[]> {
  const raw = await model.detect(source, 12, CONF_THRESHOLD);
  const frameArea = Math.max(frameW * frameH, 1);
  const detections: Detection[] = [];

  for (const r of raw) {
    const label = r.class;
    if (!RELEVANT_LABELS.has(label)) continue;

    const [x, y, w, h] = r.bbox;
    const areaRatio = (w * h) / frameArea;
    const isDangerBox = areaRatio > DANGER_AREA_THRESHOLD;
    const position = positionFromBbox(x, y, w, h, frameW, frameH);
    const bottomNorm = (y + h) / Math.max(frameH, 1);
    const tier = distanceBand(label, areaRatio, bottomNorm, prevTiers.get(label));
    prevTiers.set(label, tier);

    detections.push({
      label,
      confidence: Math.round(r.score * 1000) / 1000,
      position,
      is_danger: isDangerBox,
      tier,
      areaRatio: Math.round(areaRatio * 10000) / 10000,
      bbox: { x, y, w, h },
    });
  }

  // Forget hysteresis for labels no longer in view, so a returning object
  // starts fresh instead of inheriting a stale tier.
  const seen = new Set(detections.map((d) => d.label));
  for (const label of [...prevTiers.keys()]) {
    if (!seen.has(label)) prevTiers.delete(label);
  }

  return detections;
}

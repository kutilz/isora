"use client";

/**
 * Banknote detection for the simulator: the same trained YOLO26n as the device
 * (tools/money_model), exported to ONNX and run by ONNX Runtime Web instead of
 * the NPU. The graph stops at the raw head exactly as export_y26.py cuts it for
 * MaixPy, so the anchors, stride scaling and NMS that MaixPy's decoder does on
 * the device are done here.
 *
 * Runtime and weights are self-hosted under /models/, which the service worker
 * keeps cache-first, so after the first run this mode works offline too.
 */

import { MONEY_CONF_THRESHOLD, MONEY_IOU_THRESHOLD, MONEY_LABELS, nominalFromLabel } from "./money";

const ORT_DIR = "/models/ort/";
const MODEL_URL = "/models/uang_yolo26n_320x224.onnx";
const INPUT_W = 320;
const INPUT_H = 224;
const STRIDES = [8, 16, 32];
// About 12 MB compressed for the first run, which takes a while on a weak signal.
const LOAD_TIMEOUT_MS = 180_000;

type OrtTensor = { data: Float32Array };
type OrtSession = {
  run: (feeds: Record<string, unknown>) => Promise<Record<string, OrtTensor>>;
};
type Ort = {
  env: { wasm: { wasmPaths: string; numThreads: number } };
  Tensor: new (type: string, data: Float32Array, dims: number[]) => unknown;
  InferenceSession: { create: (url: string, options: unknown) => Promise<OrtSession> };
};

export type MoneyModel = { ort: Ort; session: OrtSession };
export type MoneyBox = { value: number; confidence: number; bbox: { x: number; y: number; w: number; h: number } };

let modelPromise: Promise<MoneyModel> | null = null;
let work: HTMLCanvasElement | null = null;

function loadRuntime(): Promise<Ort> {
  const existing = (window as unknown as { ort?: Ort }).ort;
  if (existing) return Promise.resolve(existing);
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = `${ORT_DIR}ort.wasm.min.js`;
    script.onload = () => resolve((window as unknown as { ort: Ort }).ort);
    script.onerror = () => reject(new Error("ONNX Runtime failed to load"));
    document.head.append(script);
  });
}

/** Loads (and caches) the model. Safe to call repeatedly. */
export function loadMoneyModel(): Promise<MoneyModel> {
  if (!modelPromise) {
    const load = (async () => {
      const ort = await loadRuntime();
      ort.env.wasm.wasmPaths = ORT_DIR;
      // Threads need cross-origin isolation, which this site does not set up.
      ort.env.wasm.numThreads = 1;
      const session = await ort.InferenceSession.create(MODEL_URL, { executionProviders: ["wasm"] });
      return { ort, session };
    })();
    const timeout = new Promise<never>((_, reject) => {
      window.setTimeout(() => reject(new Error("money model load timed out")), LOAD_TIMEOUT_MS);
    });
    modelPromise = Promise.race([load, timeout]).catch((e) => {
      modelPromise = null; // let the user retry after a failed download
      throw e;
    });
  }
  return modelPromise;
}

/**
 * The centre band of the frame that goes to the model. The model is 320×224, so
 * a portrait phone frame cannot be fitted whole without shrinking a note to
 * almost nothing. The overlay shows this band so a note can be held inside it.
 */
export function scanBand(frameW: number, frameH: number) {
  const ratio = INPUT_W / INPUT_H;
  const w = Math.min(frameW, frameH * ratio);
  const h = w / ratio;
  return { x: (frameW - w) / 2, y: (frameH - h) / 2, w, h };
}

function iou(a: Candidate, b: Candidate): number {
  const w = Math.min(a.x2, b.x2) - Math.max(a.x1, b.x1);
  const h = Math.min(a.y2, b.y2) - Math.max(a.y1, b.y1);
  if (w <= 0 || h <= 0) return 0;
  const inter = w * h;
  return inter / ((a.x2 - a.x1) * (a.y2 - a.y1) + (b.x2 - b.x1) * (b.y2 - b.y1) - inter);
}

type Candidate = { x1: number; y1: number; x2: number; y2: number; score: number; cls: number };

/** Anchors, stride scaling and per-class NMS, in model-input pixels. */
export function decode(boxes: Float32Array, scores: Float32Array, confTh: number, iouTh: number): Candidate[] {
  const classes = MONEY_LABELS.length;
  const total = scores.length / classes;
  const found: Candidate[] = [];
  let i = 0;
  for (const stride of STRIDES) {
    const cols = INPUT_W / stride;
    const rows = INPUT_H / stride;
    for (let row = 0; row < rows; row++) {
      for (let col = 0; col < cols; col++, i++) {
        let cls = 0;
        let score = 0;
        for (let c = 0; c < classes; c++) {
          const s = scores[c * total + i];
          if (s > score) {
            score = s;
            cls = c;
          }
        }
        if (score < confTh) continue;
        // Boxes are [1,1,4,N]: ltrb distances from the cell centre, in grid units.
        const cx = col + 0.5;
        const cy = row + 0.5;
        found.push({
          x1: (cx - boxes[i]) * stride,
          y1: (cy - boxes[total + i]) * stride,
          x2: (cx + boxes[2 * total + i]) * stride,
          y2: (cy + boxes[3 * total + i]) * stride,
          score,
          cls,
        });
      }
    }
  }
  found.sort((a, b) => b.score - a.score);
  const kept: Candidate[] = [];
  for (const candidate of found) {
    if (!kept.some((k) => k.cls === candidate.cls && iou(k, candidate) > iouTh)) kept.push(candidate);
  }
  return kept;
}

/** One frame: crop to the band, run the model, return boxes in frame pixels. */
export async function detectMoney(
  model: MoneyModel,
  source: HTMLVideoElement | HTMLCanvasElement,
  frameW: number,
  frameH: number,
  confTh = MONEY_CONF_THRESHOLD
): Promise<MoneyBox[]> {
  if (!work) {
    work = document.createElement("canvas");
    work.width = INPUT_W;
    work.height = INPUT_H;
  }
  const ctx = work.getContext("2d", { willReadFrequently: true });
  if (!ctx) return [];
  const band = scanBand(frameW, frameH);
  ctx.drawImage(source, band.x, band.y, band.w, band.h, 0, 0, INPUT_W, INPUT_H);
  const { data } = ctx.getImageData(0, 0, INPUT_W, INPUT_H);

  // Planar RGB scaled to 0..1 (the .mud's mean 0, scale 1/255).
  const pixels = INPUT_W * INPUT_H;
  const input = new Float32Array(pixels * 3);
  for (let p = 0; p < pixels; p++) {
    input[p] = data[p * 4] / 255;
    input[pixels + p] = data[p * 4 + 1] / 255;
    input[2 * pixels + p] = data[p * 4 + 2] / 255;
  }

  const out = await model.session.run({
    images: new model.ort.Tensor("float32", input, [1, 3, INPUT_H, INPUT_W]),
  });
  const k = band.w / INPUT_W;
  const result: MoneyBox[] = [];
  for (const d of decode(out.boxes.data, out.scores.data, confTh, MONEY_IOU_THRESHOLD)) {
    const value = nominalFromLabel(MONEY_LABELS[d.cls]);
    if (value === null) continue;
    result.push({
      value,
      confidence: Math.round(d.score * 1000) / 1000,
      bbox: { x: band.x + d.x1 * k, y: band.y + d.y1 * k, w: (d.x2 - d.x1) * k, h: (d.y2 - d.y1) * k },
    });
  }
  return result;
}

/**
 * Generates the PWA icon set in public/icons from one source SVG.
 *
 * The mark is the I-Sora beacon (components/Logo.tsx) on the indigo brand
 * ground. Two variants are emitted because Android uses them differently:
 *   - "any"      → the full-bleed mark (used as-is, e.g. in the task switcher)
 *   - "maskable" → the same mark shrunk into the 80% safe zone so a circular
 *                  or squircle mask can crop the edges without eating a ring.
 *
 * Regenerate with:  node scripts/gen-icons.mjs
 */
import { mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import sharp from "sharp";

const OUT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "public", "icons");

const INDIGO = "#2C3680";
const AMBER = "#F4A23B";

/** The beacon mark, drawn at `scale` of the canvas and centred. */
function svg(size, scale, rounded) {
  const s = size * scale;
  const off = (size - s) / 2;
  const r = rounded ? size * 0.22 : 0;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
  <rect width="${size}" height="${size}" rx="${r}" ry="${r}" fill="${INDIGO}"/>
  <g transform="translate(${off} ${off}) scale(${s / 100})">
    <circle cx="50" cy="50" r="40" fill="none" stroke="${AMBER}" stroke-width="3" opacity="0.25"/>
    <circle cx="50" cy="50" r="26" fill="none" stroke="${AMBER}" stroke-width="3.4" opacity="0.55"/>
    <circle cx="50" cy="50" r="13" fill="none" stroke="${AMBER}" stroke-width="3.6" opacity="0.9"/>
    <circle cx="50" cy="50" r="6" fill="${AMBER}"/>
  </g>
</svg>`;
}

const TARGETS = [
  // name                  size  scale  rounded
  ["icon-192.png", 192, 0.78, true],
  ["icon-512.png", 512, 0.78, true],
  ["icon-maskable-192.png", 192, 0.56, false],
  ["icon-maskable-512.png", 512, 0.56, false],
  ["apple-touch-icon.png", 180, 0.74, false], // iOS applies its own mask
];

await mkdir(OUT, { recursive: true });

for (const [name, size, scale, rounded] of TARGETS) {
  const png = await sharp(Buffer.from(svg(size, scale, rounded))).png().toBuffer();
  await writeFile(path.join(OUT, name), png);
  console.log(`wrote ${name} (${size}px)`);
}

// A crisp vector favicon for desktop tabs — no raster step needed.
await writeFile(path.join(OUT, "icon.svg"), svg(64, 0.78, true));
console.log("wrote icon.svg");

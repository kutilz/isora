import { defineConfig } from "vite";
import preact from "@preact/preset-vite";
import { resolve } from "path";

/**
 * Multi-page build for AuralAI companion / admin / guide / setup.
 *
 * Output → ../static/app/  (sibling of static/index.html). The device
 * web_server.py serves these as plain static files at the corresponding
 * URLs:
 *   /           → companion.html  (after setup_completed=true)
 *   /admin      → admin.html
 *   /guide      → guide.html
 *   /setup      → setup.html
 *   /app/<...>  → hashed JS/CSS chunks
 *
 * The MaixCAM device never runs `npm` — we build on a dev PC and the
 * resulting `static/app/` is committed to the repo (treated as a vendored
 * artifact, like a compiled tarball).
 */
export default defineConfig({
  plugins: [preact()],
  base: "/app/",
  build: {
    outDir: "../static/app",
    emptyOutDir: true,
    rollupOptions: {
      input: {
        companion: resolve(__dirname, "companion.html"),
        admin:     resolve(__dirname, "admin.html"),
        guide:     resolve(__dirname, "guide.html"),
        setup:     resolve(__dirname, "setup.html"),
      },
    },
    // Inline assets under 2 KB to save round-trips on the slow MaixCAM link.
    assetsInlineLimit: 2048,
    sourcemap: false,
    target: "es2020",
  },
  server: {
    port: 5173,
    // During `npm run dev`, proxy device API calls so we don't fight CORS.
    proxy: {
      "/snapshot":  "http://localhost:8080",
      "/status":    "http://localhost:8080",
      "/logs":      "http://localhost:8080",
      "/history":   "http://localhost:8080",
      "/health":    "http://localhost:8080",
      "/config":    "http://localhost:8080",
      "/command":   "http://localhost:8080",
      "/audio":     "http://localhost:8080",
      "/assets":    "http://localhost:8080",
      "/ai-settings": "http://localhost:8080",
      "/auth":      "http://localhost:8080",
    },
  },
});

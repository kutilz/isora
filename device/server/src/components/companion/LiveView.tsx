import { useState } from "preact/hooks";
import { useSnapshotUrl } from "../../lib/polling";
import { Icon } from "../atoms/Icon";
import { apiPost } from "../../lib/api";
import type { DeviceStatus } from "./types";

/** Live camera + last caption block. /snapshot polls at 500 ms. */
export function LiveView({ status }: { status: DeviceStatus | null }) {
  const url = useSnapshotUrl(500);
  const [camError, setCamError] = useState(false);
  const caption = status?.last_caption.text || status?.audio_text || "(belum ada suara)";
  const captionStale = !status?.last_caption.text;
  const repeat = () => apiPost("/command", { cmd: "describe" }).catch(() => {});
  return (
    <section
      class="card"
      aria-labelledby="live-title"
      style={{ padding: "var(--s-5)", display: "grid", gap: "var(--s-4)" }}
    >
      <header style={{ display: "flex", alignItems: "center", gap: "var(--s-3)" }}>
        <Icon name="glasses" size={24} />
        <h2 id="live-title" style={{ margin: 0, fontSize: "var(--t-lg)" }}>
          Yang dilihat pengguna
        </h2>
        {camError ? (
          <span class="badge badge--warn" style={{ marginLeft: "auto" }}>
            <span class="dot dot--warn" /> Kamera tidak aktif
          </span>
        ) : (
          <span class="badge badge--ok" style={{ marginLeft: "auto" }}>
            <span class="dot dot--ok" /> Live
          </span>
        )}
      </header>
      <div
        style={{
          background: "#1a1a1a",
          borderRadius: "var(--r-md)",
          aspectRatio: "16/9",
          overflow: "hidden",
          border: "1px solid var(--border)",
          position: "relative",
        }}
      >
        <img
          src={url}
          alt="Pratinjau kamera AuralAI"
          style={{ width: "100%", height: "100%", objectFit: "cover", display: camError ? "none" : "block" }}
          onLoad={() => setCamError(false)}
          onError={() => setCamError(true)}
        />
        {camError && (
          <div
            style={{
              position: "absolute", inset: 0,
              display: "flex", flexDirection: "column",
              alignItems: "center", justifyContent: "center",
              gap: 8, color: "var(--ink-3)",
            }}
          >
            <Icon name="glasses" size={32} />
            <span style={{ fontSize: "var(--t-sm)" }}>Kamera belum siap</span>
          </div>
        )}
      </div>

      <div
        aria-live="polite"
        aria-atomic="true"
        style={{
          padding: "var(--s-4) var(--s-5)",
          background: "var(--surface-2)",
          borderRadius: "var(--r-md)",
          borderLeft: "6px solid var(--accent)",
        }}
      >
        <div
          style={{
            fontSize: "var(--t-xs)",
            textTransform: "uppercase",
            letterSpacing: ".08em",
            color: "var(--ink-3)",
            fontWeight: 700,
            marginBottom: 4,
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          <Icon name="speaker" size={14} />
          Suara terakhir
        </div>
        <div
          style={{
            fontSize: "var(--t-lg)",
            fontWeight: 600,
            color: captionStale ? "var(--ink-3)" : "var(--ink)",
            fontStyle: captionStale ? "italic" : "normal",
          }}
        >
          {captionStale ? caption : `"${caption}"`}
        </div>
      </div>

      <div style={{ display: "flex", gap: "var(--s-3)", flexWrap: "wrap" }}>
        <button type="button" class="btn" onClick={repeat}>
          <Icon name="refresh" size={18} /> Ulangi deskripsi
        </button>
      </div>
    </section>
  );
}

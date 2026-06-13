import { useState } from "preact/hooks";
import { AssetImage } from "../atoms/AssetImage";

/**
 * Storyboard — port of designs/storyboard.jsx. Three scenarios; each
 * starts collapsed showing only panel 1 with a "Lihat semua panel"
 * toggle (handoff §2.2).
 *
 * For brevity the inline PanelArt SVGs from the prototype are kept but
 * the per-art renderers are inlined here.
 */
export function StoryboardSection() {
  return (
    <section
      style={{ padding: "var(--s-12) var(--s-5)", background: "var(--bg)" }}
    >
      <div style={{ maxWidth: 1280, margin: "0 auto" }}>
        <h2 class="section-title">Bagaimana cara pakainya?</h2>
        <p class="section-sub">
          Tiga situasi nyata. Setiap panel menunjukkan tombol yang dipencet,
          chime yang berbunyi, dan suara bicara yang keluar.
        </p>

        <div class="stack" style={{ marginTop: "var(--s-6)" }}>
          <Scenario
            id={1}
            title="Skenario 1 — Berjalan di koridor sekolah"
            mode="Jelajah"
            modeColor="var(--accent)"
            panels={[
              { caption: "Bu Sari berjalan keluar kelas, kacamata sudah aktif Mode Jelajah.", chime: "Mode Jelajah", speech: "—" },
              { caption: "Kamera mendeteksi pintu di depan, lalu kursi di kiri.",            chime: "Objek dekat", speech: "Pintu di depan" },
              { caption: "Seseorang lewat dari kanan — prioritas tinggi.",                    chime: "Objek dekat", speech: "Orang di kanan, dekat" },
              { caption: "Bu Sari menahan tombol Aksi 1 detik untuk meminta ulang.",          chime: "Mendengarkan", speech: "Orang di kanan, dekat" },
              { caption: "Tiba di tangga — prioritas kritikal.",                              chime: "Alarm 3×",     speech: "Hati-hati, ada turunan di depan" },
            ]}
            art={["walking", "doorway", "person", "buttonpress", "stairs"]}
          />
          <Scenario
            id={2}
            title="Skenario 2 — Mau makan di kantin"
            mode="Deskripsi"
            modeColor="var(--info)"
            panels={[
              { caption: "Pencet Mode 1× → masuk Mode Deskripsi (chime 2 nada).",  chime: "Mode Deskripsi", speech: "Mode deskripsi" },
              { caption: "Tekan Aksi → kamera ambil foto, AI memproses.",          chime: "Memproses",       speech: "—" },
              { caption: "AI selesai → chord pendek, lalu deskripsi.",             chime: "Hasil siap",      speech: "Meja kantin dengan piring nasi dan air putih di depan." },
              { caption: "Bu Sari pencet Aksi 2× → panggil pendamping.",           chime: "Konfirmasi",      speech: "Pendamping dipanggil" },
            ]}
            art={["modeswitch", "buttonpress", "table", "phone"]}
          />
          <Scenario
            id={3}
            title="Skenario 3 — Bayar di warung"
            mode="QRIS"
            modeColor="var(--warn)"
            panels={[
              { caption: "Tekan Mode 2× → masuk Mode QRIS (3 nada).",              chime: "Mode QRIS",   speech: "Mode bayar" },
              { caption: "Arahkan kepala ke arah QR — chime panduan saat sudut salah.", chime: "Buzz pendek", speech: "Geser sedikit ke kiri" },
              { caption: "QR terbaca, AI baca nominal.",                            chime: "Hasil siap",  speech: "Warung Bu Ida, lima belas ribu rupiah." },
              { caption: "Nominal > 1 juta? minta konfirmasi ulang. (di sini tidak)", chime: "—",         speech: "Konfirmasi bayar dengan Aksi" },
              { caption: "Bu Sari pencet Aksi → lanjut bayar di HP-nya sendiri.",   chime: "Konfirmasi",  speech: "Siap bayar" },
            ]}
            art={["modeswitch", "qrscan", "qrok", "confirm", "paid"]}
          />
        </div>
      </div>
    </section>
  );
}

interface Panel { caption: string; chime: string; speech: string }

function Scenario({
  id, title, mode, modeColor, panels, art,
}: {
  id: number;
  title: string;
  mode: string;
  modeColor: string;
  panels: Panel[];
  art: string[];
}) {
  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? panels : panels.slice(0, 1);
  return (
    <section class="card" style={{ padding: "var(--s-5)" }}>
      <header
        style={{
          display: "flex",
          alignItems: "center",
          gap: "var(--s-3)",
          marginBottom: "var(--s-4)",
          flexWrap: "wrap",
        }}
      >
        <h3 style={{ margin: 0, fontSize: "var(--t-xl)" }}>{title}</h3>
        <span
          class="badge"
          style={{
            background: modeColor,
            color: "var(--ink-inverse)",
            border: "none",
            padding: "4px 12px",
          }}
        >
          Mode {mode}
        </span>
        <button
          type="button"
          class="btn btn--ghost"
          aria-expanded={expanded}
          aria-controls={`scenario-${id}-panels`}
          style={{ marginLeft: "auto" }}
          onClick={() => setExpanded((e) => !e)}
        >
          {expanded ? "Tutup panel lain" : `Lihat semua ${panels.length} panel`}
        </button>
      </header>

      <div
        id={`scenario-${id}-panels`}
        style={{
          display: "grid",
          gridTemplateColumns: `repeat(${shown.length}, minmax(0, 1fr))`,
          gap: "var(--s-3)",
        }}
      >
        {shown.map((p, i) => (
          <PanelCard key={i} index={i + 1} panel={p} art={art[i]} scenarioId={id} />
        ))}
      </div>
    </section>
  );
}

function PanelCard({
  index, panel, art, scenarioId,
}: { index: number; panel: Panel; art: string; scenarioId: number }) {
  const assetName = `scenario_${scenarioId}_${index}.jpg`;
  return (
    <article
      style={{
        border: "1px solid var(--border)",
        borderRadius: "var(--r-md)",
        overflow: "hidden",
        background: "var(--surface)",
        display: "flex",
        flexDirection: "column",
        minHeight: 320,
      }}
    >
      <div
        style={{
          aspectRatio: "4/3",
          background: "var(--surface-2)",
          borderBottom: "1px solid var(--border)",
          position: "relative",
        }}
      >
        <AssetImage
          name={assetName}
          alt={panel.caption}
          style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover" }}
          fallback={<PanelMockup name={art} />}
        />
        <span
          style={{
            position: "absolute",
            top: 8,
            left: 8,
            background: "var(--ink)",
            color: "var(--ink-inverse)",
            width: 28,
            height: 28,
            borderRadius: "50%",
            display: "grid",
            placeItems: "center",
            fontWeight: 700,
            fontSize: "var(--t-sm)",
          }}
        >
          {index}
        </span>
      </div>
      <div
        style={{
          padding: "var(--s-3)",
          fontSize: "var(--t-sm)",
          lineHeight: 1.45,
          borderBottom: "1px dashed var(--border)",
        }}
      >
        {panel.caption}
      </div>
      <div style={{ padding: "var(--s-3)", display: "grid", gap: 6, fontSize: "var(--t-xs)" }}>
        <Row label="Chime" value={panel.chime} accent />
        <Row label="Bicara" value={panel.speech === "—" ? "(diam)" : `"${panel.speech}"`} />
      </div>
    </article>
  );
}

function Row({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div style={{ display: "flex", gap: 6, alignItems: "flex-start" }}>
      <span
        style={{
          display: "inline-block",
          fontSize: "var(--t-xs)",
          padding: "2px 8px",
          borderRadius: "var(--r-pill)",
          fontWeight: 700,
          flexShrink: 0,
          textTransform: "uppercase",
          letterSpacing: ".05em",
          background: accent ? "var(--accent-soft)" : "var(--surface-2)",
          color: accent ? "var(--accent-ink)" : "var(--ink-2)",
        }}
      >
        {label}
      </span>
      <span>{value}</span>
    </div>
  );
}

/** Tiny vector panel art (fallback when no photo present). Subset of designs/storyboard.jsx PanelArt. */
function PanelMockup({ name }: { name: string }) {
  return (
    <svg
      viewBox="0 0 200 150"
      preserveAspectRatio="xMidYMid meet"
      style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
      aria-hidden="true"
    >
      <rect width="200" height="150" fill="#E8EAE2" />
      <rect y="120" width="200" height="30" fill="#a8a08a" />
      {/* Simple "person + glasses" — generic across all panels. */}
      <g transform="translate(70,32)">
        <circle cx="0" cy="0" r="10" fill="#3D3D3D" />
        <rect x="-12" y="10" width="24" height="34" rx="6" fill="#3D3D3D" />
      </g>
      <text x="100" y="80" text-anchor="middle" fill="#5F5F5F" font-size="11" font-weight="600">
        {name}
      </text>
    </svg>
  );
}

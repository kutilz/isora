import { AssetImage } from "../atoms/AssetImage";
import { t } from "../../lib/i18n";

/**
 * Hardware section — port of designs/hardware-diagram.jsx, but laid out
 * inside the long-scroll /guide rather than as a standalone artboard.
 *
 * Photos override the SVG mockup when files exist in /assets/.
 */
export function HardwareSection() {
  return (
    <section
      id="hardware"
      style={{ padding: "var(--s-12) var(--s-5)", background: "var(--bg)" }}
    >
      <div style={{ maxWidth: 1100, margin: "0 auto" }}>
        <h2 class="section-title">{t("guide.hw_title")}</h2>
        <p class="section-sub">
          Empat tombol — semuanya bisa dibedakan dengan ujung jari. Setiap
          tombol punya tactile cue berbeda supaya tidak salah pencet.
        </p>

        {/* Drawings */}
        <div
          class="grid-2"
          style={{ gap: "var(--s-5)", alignItems: "center" }}
        >
          <AssetImage
            name="glasses_front.jpg"
            alt="Foto kacamata tampak depan dengan modul AuralAI di tangkai kanan"
            style={{ width: "100%", borderRadius: "var(--r-md)" }}
            fallback={<GlassesFront />}
          />
          <AssetImage
            name="glasses_side.jpg"
            alt="Foto modul AuralAI tampak samping"
            style={{ width: "100%", borderRadius: "var(--r-md)" }}
            fallback={<GlassesSide />}
          />
        </div>

        {/* Button map */}
        <div class="card" style={{ padding: "var(--s-5)", marginTop: "var(--s-8)" }}>
          <h3 style={{ margin: "0 0 var(--s-3)", fontSize: "var(--t-lg)" }}>
            Peta tombol fisik
          </h3>
          <ButtonMap />
        </div>

        {/* Spec cards */}
        <div class="grid-2" style={{ gap: "var(--s-5)", marginTop: "var(--s-6)" }}>
          <SpecCard
            title="Tactile cue per tombol"
            items={[
              ["Power", "Tombol bundar besar, recessed (dalam) — sulit terpencet tak sengaja"],
              ["Aksi", "Tombol oval menonjol — paling mudah dijangkau ibu jari"],
              ["Mode", "Tombol persegi dengan 3 titik braille — menyimbolkan 3 mode"],
              ["Volume", "Slider roda bergerigi — terasa berputar, tahan posisi"],
            ]}
          />
          <SpecCard
            title="Pola dipakai (mounting)"
            items={[
              ["Posisi", "Tangkai kanan kacamata, di belakang engsel"],
              ["Berat", "≤ 28 gram supaya kacamata tidak melorot"],
              ["Klip", "Klip karet silikon, muat tangkai 4–7 mm"],
              ["Kabel", "Tidak ada — semua wireless (WiFi + speaker built-in)"],
            ]}
          />
          <SpecCard
            title="Indikator non-visual"
            items={[
              ["Suara", "Chime pendek tiap event sistem"],
              ["Getar", "Motor haptic kecil — 1 getar = mode ganti, 2 = error"],
              ["LED", "Untuk pendamping saja — di sisi luar"],
              ["Suhu", "Casing alumunium — pendamping bisa rasakan kalau overheat"],
            ]}
          />
          <SpecCard
            title="Charging & power"
            items={[
              ["Port", "USB-C tunggal, di ujung bawah modul"],
              ["Cue isi", "Chime saat tersambung, getar saat penuh"],
              ["Baterai lemah", "Beep + suara 'baterai 20%' tiap 5 menit"],
              ["Sleep", "Auto-sleep setelah 2 menit tidak ada interaksi"],
            ]}
          />
        </div>
      </div>
    </section>
  );
}

/* ─── Inline mockups (used as fallbacks) — ported from hardware-diagram.jsx ─ */

function GlassesFront() {
  return (
    <figure style={{ margin: 0 }}>
      <svg
        viewBox="0 0 480 280"
        style={{ width: "100%", height: "auto", borderRadius: "var(--r-md)", background: "var(--surface)" }}
        aria-label="Ilustrasi tampak depan kacamata dengan modul AuralAI di tangkai kanan"
      >
        <ellipse cx="240" cy="170" rx="44" ry="10" fill="#EAE7DF" />
        <circle cx="170" cy="140" r="58" fill="#F4F2EB" stroke="#3D3D3D" stroke-width="6" />
        <circle cx="310" cy="140" r="58" fill="#F4F2EB" stroke="#3D3D3D" stroke-width="6" />
        <path d="M228 138 Q240 124 252 138" stroke="#3D3D3D" stroke-width="6" fill="none" />
        <path d="M112 140 L60 130" stroke="#3D3D3D" stroke-width="6" stroke-linecap="round" />
        <path d="M368 140 L398 134" stroke="#3D3D3D" stroke-width="6" stroke-linecap="round" />
        <g transform="translate(395,108)">
          <rect width="72" height="58" rx="8" fill="#00635D" stroke="#002D2A" stroke-width="2" />
          <circle cx="14" cy="14" r="7" fill="#141414" />
          <circle cx="14" cy="14" r="4" fill="#3A6E6A" />
          <circle cx="14" cy="14" r="1.5" fill="#fff" />
          <circle cx="32" cy="14" r="1.5" fill="#fff" opacity="0.7" />
          <circle cx="38" cy="14" r="1.5" fill="#fff" opacity="0.7" />
          <circle cx="62" cy="34" r="3" fill="#3DCB6E" />
          <text x="6" y="48" font-family="Inter, sans-serif" font-size="9" font-weight="700" fill="#fff">
            AURALAI
          </text>
        </g>
      </svg>
      <figcaption style={{ textAlign: "center", fontSize: "var(--t-sm)", color: "var(--ink-3)", marginTop: 6 }}>
        Tampak depan — modul di tangkai kanan
      </figcaption>
    </figure>
  );
}

function GlassesSide() {
  return (
    <figure style={{ margin: 0 }}>
      <svg
        viewBox="0 0 360 320"
        style={{ width: "100%", height: "auto", borderRadius: "var(--r-md)", background: "var(--surface)" }}
        aria-label="Ilustrasi modul AuralAI tampak samping"
      >
        <rect x="0" y="60" width="360" height="14" rx="7" fill="#3D3D3D" />
        <rect x="60" y="50" width="240" height="100" rx="14" fill="#00635D" stroke="#002D2A" stroke-width="2" />
        <circle cx="84" cy="100" r="10" fill="#141414" />
        <circle cx="84" cy="100" r="6" fill="#3A6E6A" />
        <g transform="translate(120,30)">
          <circle r="14" fill="#1f2a2a" stroke="#fff" stroke-width="2" />
          <circle r="6" fill="none" stroke="#fff" stroke-width="2" />
          <line x1="0" y1="-7" x2="0" y2="0" stroke="#fff" stroke-width="2" />
        </g>
        <g transform="translate(180,30)">
          <rect x="-12" y="-12" width="24" height="24" rx="4" fill="#FFF" stroke="#002D2A" stroke-width="2" />
          <circle cx="-5" cy="0" r="2" fill="#002D2A" />
          <circle cx="0" cy="0" r="2" fill="#002D2A" />
          <circle cx="5" cy="0" r="2" fill="#002D2A" />
        </g>
        <g transform="translate(240,30)">
          <rect x="-18" y="-10" width="36" height="20" rx="10" fill="#FFD300" stroke="#3D3D3D" stroke-width="2" />
          <text x="0" y="4" font-family="Inter,sans-serif" font-size="10" font-weight="700" fill="#141414" text-anchor="middle">
            AKSI
          </text>
        </g>
        <rect x="160" y="148" width="40" height="8" rx="3" fill="#141414" />
        <text x="180" y="172" font-size="9" text-anchor="middle" fill="#141414" font-weight="600">
          USB-C
        </text>
      </svg>
      <figcaption style={{ textAlign: "center", fontSize: "var(--t-sm)", color: "var(--ink-3)", marginTop: 6 }}>
        Tampak samping — letak tombol di tepi atas
      </figcaption>
    </figure>
  );
}

function ButtonMap() {
  const rows = [
    { n: "①", name: "Power", shape: "Bundar, sedikit cekung",
      short: "—", long: "Tahan 2 dtk → on/off", double: "—",
      rationale: "Cekung = sulit terpencet tak sengaja" },
    { n: "②", name: "Mode", shape: "Persegi dengan 3 titik braille",
      short: "Mode berikutnya (Jelajah → Deskripsi → QRIS)",
      long: "Tahan 1 dtk → kembali ke mode sebelumnya",
      double: "Sebutkan mode aktif",
      rationale: "3 titik braille mengingatkan 3 mode" },
    { n: "③", name: "Aksi", shape: "Oval menonjol, warna kuning",
      short: "Mode Deskripsi: jelaskan sekarang; Mode QRIS: ambil foto kode",
      long: "Tahan 1 dtk → ulangi suara terakhir",
      double: "Panggil pendamping",
      rationale: "Paling sering dipencet → letak paling enak di ibu jari" },
    { n: "④", name: "Volume", shape: "Roda bergerigi (analog)",
      short: "Putar maju/mundur untuk keras/pelan",
      long: "Tekan roda → bisukan sementara",
      double: "—",
      rationale: "Analog = pengguna terus tahu posisinya dengan jari" },
  ];
  const th: any = { padding: "10px 12px", fontWeight: 700, fontSize: "var(--t-xs)",
                     textTransform: "uppercase", letterSpacing: ".05em",
                     color: "var(--ink-3)", textAlign: "left" };
  const td: any = { padding: 12, verticalAlign: "top", fontSize: "var(--t-sm)" };
  return (
    <div style={{ overflow: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 720 }}>
        <thead>
          <tr style={{ background: "var(--surface-2)" }}>
            <th style={th}>#</th>
            <th style={th}>Tombol</th>
            <th style={th}>Bentuk fisik</th>
            <th style={th}>1× tekan</th>
            <th style={th}>Tahan</th>
            <th style={th}>2× tekan</th>
          </tr>
        </thead>
        <tbody>
          {rows.flatMap((r, i) => [
            <tr key={`r${i}`} style={{ borderTop: "1px solid var(--border)" }}>
              <td style={{ ...td, fontWeight: 700, fontSize: "var(--t-md)" }}>{r.n}</td>
              <td style={{ ...td, fontWeight: 700 }}>{r.name}</td>
              <td style={td}>{r.shape}</td>
              <td style={td}>{r.short}</td>
              <td style={td}>{r.long}</td>
              <td style={td}>{r.double}</td>
            </tr>,
            <tr key={`w${i}`} style={{ background: "var(--surface-2)" }}>
              <td></td>
              <td colSpan={5} style={{ ...td, color: "var(--ink-3)", fontStyle: "italic", paddingTop: 0 }}>
                Kenapa: {r.rationale}
              </td>
            </tr>,
          ])}
        </tbody>
      </table>
    </div>
  );
}

function SpecCard({ title, items }: { title: string; items: [string, string][] }) {
  return (
    <div class="card" style={{ padding: "var(--s-5)" }}>
      <h3 style={{ margin: "0 0 var(--s-3)", fontSize: "var(--t-md)" }}>{title}</h3>
      <dl style={{ margin: 0, display: "grid", gap: "var(--s-2)" }}>
        {items.map(([k, v], i) => (
          <div
            key={i}
            style={{
              display: "grid",
              gridTemplateColumns: "110px 1fr",
              gap: "var(--s-3)",
              paddingBottom: "var(--s-2)",
              borderBottom:
                i < items.length - 1 ? "1px solid var(--border)" : "none",
            }}
          >
            <dt
              style={{
                fontWeight: 600,
                color: "var(--ink-3)",
                fontSize: "var(--t-xs)",
                textTransform: "uppercase",
                letterSpacing: ".05em",
              }}
            >
              {k}
            </dt>
            <dd style={{ margin: 0, fontSize: "var(--t-sm)" }}>{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

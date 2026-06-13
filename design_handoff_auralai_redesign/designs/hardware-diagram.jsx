/* Hardware Diagram — annotated smart glasses for AuralAI.
   AuralAI is a MaixCAM-based module that mounts on the side of regular glasses.
   This artboard shows: front view + side view + tactile button map with rationale.
*/

window.HardwareDiagram = function HardwareDiagram() {
  return (
    <div style={{ padding: "var(--s-6)", background: "var(--bg)", minHeight: "100%" }}>
      <div style={{ maxWidth: 1100, margin: "0 auto", display: "grid", gap: "var(--s-6)" }}>

        <header>
          <div style={kicker}>Perangkat keras · v2</div>
          <h1 style={{ margin: "4px 0 0", fontSize: "var(--t-2xl)" }}>
            Modul AuralAI untuk kacamata
          </h1>
          <p style={{ margin: "var(--s-2) 0 0", color: "var(--ink-2)", fontSize: "var(--t-md)",
                      maxWidth: 720 }}>
            Modul kecil menempel di tangkai kanan kacamata pengguna. Semua kontrol dirancang agar
            bisa ditemukan tanpa melihat — tactile cue (relief, tekstur, jarak antar tombol)
            mengikuti pedoman desain produk untuk pengguna tunanetra.
          </p>
        </header>

        {/* Glasses front view with module callouts */}
        <section className="card" style={{ padding: "var(--s-6)" }}>
          <h2 style={sectionTitle}>Tampak depan & samping</h2>
          <div style={{
            display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: "var(--s-6)",
            alignItems: "center", marginTop: "var(--s-4)",
          }}>
            <GlassesFront />
            <GlassesSide />
          </div>
        </section>

        {/* Button map */}
        <section className="card" style={{ padding: "var(--s-6)" }}>
          <h2 style={sectionTitle}>Peta tombol fisik</h2>
          <p style={{ margin: "var(--s-2) 0 var(--s-4)", color: "var(--ink-3)" }}>
            Empat tombol — semuanya bisa dibedakan dengan ujung jari. Setiap tombol punya
            tactile cue berbeda supaya tidak salah pencet.
          </p>
          <ButtonMap />
        </section>

        {/* Physical spec rationale */}
        <section style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--s-5)" }}>
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
              ["Suara", "Chime pendek tiap event sistem (lihat artboard berikutnya)"],
              ["Getar", "Motor haptic kecil — 1 getar = mode ganti, 2 = error"],
              ["LED", "Untuk pendamping saja — di sisi luar, tidak silaukan pengguna"],
              ["Suhu", "Casing alumunium — pendamping bisa rasakan jika overheat"],
            ]}
          />
          <SpecCard
            title="Charging & power"
            items={[
              ["Port", "USB-C tunggal, di ujung bawah modul"],
              ["Cue isi", "Chime saat tersambung, getar saat penuh"],
              ["Baterai lemah", "Beep + suara 'baterai 20%' tiap 5 menit"],
              ["Sleep", "Auto-sleep setelah 2 menit tidak ada gerakan + tidak ada interaksi"],
            ]}
          />
        </section>
      </div>
    </div>
  );
};

/* ─── Glasses Front View ───────────────────────────────────────────────── */
function GlassesFront() {
  return (
    <figure style={{ margin: 0 }}>
      <svg viewBox="0 0 480 280" style={{ width: "100%", height: "auto" }}
           aria-label="Tampak depan kacamata dengan modul AuralAI di tangkai kanan">
        {/* nose / face hint */}
        <ellipse cx="240" cy="170" rx="44" ry="10" fill="#EAE7DF" />
        {/* left lens */}
        <circle cx="170" cy="140" r="58" fill="#F4F2EB" stroke="#3D3D3D" strokeWidth="6" />
        {/* right lens */}
        <circle cx="310" cy="140" r="58" fill="#F4F2EB" stroke="#3D3D3D" strokeWidth="6" />
        {/* bridge */}
        <path d="M228 138 Q240 124 252 138" stroke="#3D3D3D" strokeWidth="6" fill="none" />
        {/* left temple */}
        <path d="M112 140 L60 130" stroke="#3D3D3D" strokeWidth="6" strokeLinecap="round" />
        {/* right temple stub */}
        <path d="M368 140 L398 134" stroke="#3D3D3D" strokeWidth="6" strokeLinecap="round" />
        {/* AuralAI module (mounted on right temple) */}
        <g transform="translate(395,108)">
          <rect x="0" y="0" width="72" height="58" rx="8"
                fill="#00635D" stroke="#002D2A" strokeWidth="2" />
          {/* camera lens */}
          <circle cx="14" cy="14" r="7" fill="#141414" />
          <circle cx="14" cy="14" r="4" fill="#3A6E6A" />
          <circle cx="14" cy="14" r="1.5" fill="#fff" />
          {/* mic dots */}
          <circle cx="32" cy="14" r="1.5" fill="#fff" opacity=".7" />
          <circle cx="38" cy="14" r="1.5" fill="#fff" opacity=".7" />
          {/* speaker grille */}
          <g fill="#fff" opacity=".55">
            {[0,1,2,3].map(i => <rect key={i} x={48 + i*4} y="10" width="2" height="14" rx="1" />)}
          </g>
          {/* status LED */}
          <circle cx="62" cy="34" r="3" fill="#3DCB6E" />
          {/* AuralAI logotype */}
          <text x="6" y="48" fontFamily="Inter, sans-serif"
                fontSize="9" fontWeight="700" fill="#fff">AURALAI</text>
        </g>

        {/* Callouts (right side) */}
        <Callout x={476} y={114} side="right" label="Kamera + LED status" />
        <Callout x={476} y={134} side="right" label="Mikrofon ganda (noise-cancel)" />
        <Callout x={476} y={156} side="right" label="Speaker mungil (dekat telinga)" />
      </svg>
      <figcaption style={{ marginTop: "var(--s-2)", fontSize: "var(--t-sm)",
                            color: "var(--ink-3)", textAlign: "center" }}>
        Tampak depan — modul di tangkai kanan
      </figcaption>
    </figure>
  );
}

/* ─── Glasses Side View ────────────────────────────────────────────────── */
function GlassesSide() {
  return (
    <figure style={{ margin: 0 }}>
      <svg viewBox="0 0 360 320" style={{ width: "100%", height: "auto" }}
           aria-label="Tampak samping modul AuralAI yang menempel di tangkai kacamata">
        {/* Temple bar */}
        <rect x="0" y="60" width="360" height="14" rx="7" fill="#3D3D3D" />
        {/* Module shell */}
        <rect x="60" y="50" width="240" height="100" rx="14"
              fill="#00635D" stroke="#002D2A" strokeWidth="2" />
        {/* Front face details */}
        <circle cx="84" cy="100" r="10" fill="#141414" />
        <circle cx="84" cy="100" r="6" fill="#3A6E6A" />

        {/* TOP edge buttons */}
        {/* power (round, recessed) */}
        <g transform="translate(120,30)">
          <circle r="14" fill="#1f2a2a" stroke="#fff" strokeWidth="2" />
          <circle r="6" fill="none" stroke="#fff" strokeWidth="2" />
          <line x1="0" y1="-7" x2="0" y2="0" stroke="#fff" strokeWidth="2" />
        </g>
        {/* mode (square with 3 dots) */}
        <g transform="translate(180,30)">
          <rect x="-12" y="-12" width="24" height="24" rx="4"
                fill="#FFF" stroke="#002D2A" strokeWidth="2" />
          <circle cx="-5" cy="0" r="2" fill="#002D2A" />
          <circle cx="0"  cy="0" r="2" fill="#002D2A" />
          <circle cx="5"  cy="0" r="2" fill="#002D2A" />
        </g>
        {/* action (oval) */}
        <g transform="translate(240,30)">
          <rect x="-18" y="-10" width="36" height="20" rx="10"
                fill="#FFD300" stroke="#3D3D3D" strokeWidth="2" />
          <text x="0" y="4" fontFamily="Inter,sans-serif" fontSize="10"
                fontWeight="700" fill="#141414" textAnchor="middle">AKSI</text>
        </g>

        {/* Volume wheel on outer side */}
        <g transform="translate(300,100)">
          <circle r="18" fill="#1f2a2a" stroke="#fff" strokeWidth="2" />
          {[0,30,60,90,120,150].map(a => (
            <line key={a} x1={Math.cos(a*Math.PI/180)*12}
                          y1={Math.sin(a*Math.PI/180)*12}
                          x2={Math.cos(a*Math.PI/180)*17}
                          y2={Math.sin(a*Math.PI/180)*17}
                          stroke="#fff" strokeWidth="1.5" />
          ))}
          <text x="0" y="36" fontSize="9" textAnchor="middle"
                fill="#141414" fontWeight="600">VOL</text>
        </g>

        {/* USB-C on bottom */}
        <rect x="160" y="148" width="40" height="8" rx="3" fill="#141414" />
        <text x="180" y="172" fontSize="9" textAnchor="middle"
              fill="#141414" fontWeight="600">USB-C</text>

        {/* Clip detail at back */}
        <path d="M60 100 Q40 100 40 80 L40 50 Q40 30 60 30 L80 30 L80 50 Q60 50 60 70 L60 100 Z"
              fill="#1F1F1F" />
        <text x="48" y="200" fontSize="9" fill="#141414" fontWeight="600">Klip silikon</text>

        {/* Callouts */}
        <Callout x={120} y={6}  side="top" label="① Power (bundar, recessed)" />
        <Callout x={180} y={6}  side="top" label="② Mode (3 braille dots)" />
        <Callout x={240} y={6}  side="top" label="③ Aksi (oval kuning, menonjol)" />
        <Callout x={332} y={100} side="right" label="④ Volume wheel" />
      </svg>
      <figcaption style={{ marginTop: "var(--s-2)", fontSize: "var(--t-sm)",
                            color: "var(--ink-3)", textAlign: "center" }}>
        Tampak samping — letak tombol di tepi atas
      </figcaption>
    </figure>
  );
}

function Callout({ x, y, side, label }) {
  const len = 24;
  const tx = side === "right" ? x + len + 4
           : side === "left"  ? x - len - 4
           : x;
  const ty = side === "top"   ? y - len - 4
           : side === "bottom" ? y + len + 4
           : y + 4;
  const x2 = side === "right" ? x + len : side === "left" ? x - len : x;
  const y2 = side === "top"   ? y - len : side === "bottom" ? y + len : y;
  const anchor = side === "right" ? "start" : side === "left" ? "end" : "middle";
  return (
    <g>
      <line x1={x} y1={y} x2={x2} y2={y2} stroke="#7A776E" strokeWidth="1" strokeDasharray="3 2" />
      <circle cx={x} cy={y} r="3" fill="#00635D" />
      <text x={tx} y={ty} fontFamily="Inter,sans-serif" fontSize="11"
            fontWeight="600" fill="#141414" textAnchor={anchor}>{label}</text>
    </g>
  );
}

/* ─── Button Map table ─────────────────────────────────────────────────── */
function ButtonMap() {
  const rows = [
    {
      n: "①", name: "Power",
      shape: "Bundar, sedikit cekung",
      short: "—",
      long:  "Tahan 2 dtk → on/off",
      double:"—",
      rationale: "Cekung = sulit terpencet tak sengaja saat lepas-pasang kacamata",
    },
    {
      n: "②", name: "Mode",
      shape: "Persegi dengan 3 titik braille",
      short: "Mode berikutnya (Jelajah → Deskripsi → QRIS)",
      long:  "Tahan 1 dtk → kembali ke mode sebelumnya",
      double:"Sebutkan mode aktif",
      rationale: "3 titik braille mengingatkan 3 mode — pengguna langsung tahu fungsinya",
    },
    {
      n: "③", name: "Aksi",
      shape: "Oval menonjol, warna kuning",
      short: "Mode Deskripsi: jelaskan sekarang; Mode QRIS: ambil foto kode",
      long:  "Tahan 1 dtk → ulangi suara terakhir",
      double:"Panggil pendamping (kirim notif ke HP)",
      rationale: "Paling sering dipencet → letak paling enak di ibu jari, paling menonjol",
    },
    {
      n: "④", name: "Volume",
      shape: "Roda bergerigi (analog)",
      short: "Putar maju/mundur untuk keras/pelan",
      long:  "Tekan roda → bisukan sementara",
      double:"—",
      rationale: "Analog = pengguna terus tahu posisinya dengan jari, tidak overshoot",
    },
  ];
  return (
    <div style={{ overflow: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "var(--t-sm)",
                       minWidth: 720 }}>
        <thead>
          <tr style={{ textAlign: "left", background: "var(--surface-2)" }}>
            <th style={th}>#</th>
            <th style={th}>Tombol</th>
            <th style={th}>Bentuk fisik</th>
            <th style={th}>1× tekan</th>
            <th style={th}>Tahan</th>
            <th style={th}>2× tekan</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <React.Fragment key={i}>
              <tr style={{ borderTop: "1px solid var(--border)" }}>
                <td style={{ ...td, fontWeight: 700, fontSize: "var(--t-md)" }}>{r.n}</td>
                <td style={{ ...td, fontWeight: 700 }}>{r.name}</td>
                <td style={td}>{r.shape}</td>
                <td style={td}>{r.short}</td>
                <td style={td}>{r.long}</td>
                <td style={td}>{r.double}</td>
              </tr>
              <tr style={{ background: "var(--surface-2)" }}>
                <td></td>
                <td colSpan="5" style={{ ...td, color: "var(--ink-3)",
                                          paddingTop: 0, paddingBottom: 12,
                                          fontStyle: "italic" }}>
                  Kenapa: {r.rationale}
                </td>
              </tr>
            </React.Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SpecCard({ title, items }) {
  return (
    <div className="card" style={{ padding: "var(--s-5)" }}>
      <h3 style={{ margin: "0 0 var(--s-3)", fontSize: "var(--t-md)" }}>{title}</h3>
      <dl style={{ margin: 0, display: "grid", gap: "var(--s-2)" }}>
        {items.map(([k, v], i) => (
          <div key={i} style={{
            display: "grid", gridTemplateColumns: "110px 1fr", gap: "var(--s-3)",
            paddingBottom: "var(--s-2)",
            borderBottom: i < items.length - 1 ? "1px solid var(--border)" : "none",
          }}>
            <dt style={{ fontWeight: 600, color: "var(--ink-3)",
                          fontSize: "var(--t-xs)", textTransform: "uppercase",
                          letterSpacing: ".05em" }}>{k}</dt>
            <dd style={{ margin: 0, fontSize: "var(--t-sm)" }}>{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

const sectionTitle = { margin: 0, fontSize: "var(--t-xl)" };
const kicker = { fontSize: "var(--t-xs)", color: "var(--ink-3)",
                  textTransform: "uppercase", letterSpacing: ".08em", fontWeight: 700 };
const th = { padding: "10px 12px", fontWeight: 700, fontSize: "var(--t-xs)",
              textTransform: "uppercase", letterSpacing: ".05em", color: "var(--ink-3)" };
const td = { padding: "12px", verticalAlign: "top" };

/* Storyboard — 3 real-world scenarios for AuralAI users.
   Each row = scenario, 4-5 panels showing user + device + audio.
*/

window.Storyboard = function Storyboard() {
  return (
    <div style={{ padding: "var(--s-6)", background: "var(--bg)", minHeight: "100%" }}>
      <div style={{ maxWidth: 1280, margin: "0 auto", display: "grid", gap: "var(--s-6)" }}>
        <header>
          <div style={kS}>Skenario penggunaan · v1</div>
          <h1 style={{ margin: "4px 0 0", fontSize: "var(--t-2xl)" }}>
            Bagaimana pengguna memakainya
          </h1>
          <p style={{ margin: "var(--s-2) 0 0", color: "var(--ink-2)", fontSize: "var(--t-md)",
                      maxWidth: 760 }}>
            Tiga situasi nyata dari sesi pilot di SLB. Setiap panel menunjukkan tombol yang
            dipencet, chime yang berbunyi, dan suara bicara yang keluar.
          </p>
        </header>

        <Scenario
          title="Skenario 1 — Berjalan di koridor sekolah"
          mode="Jelajah" modeColor="var(--accent)"
          panels={[
            { caption: "Bu Sari berjalan keluar kelas, kacamata sudah aktif Mode Jelajah.",
              audio: { chime: "Mode Jelajah", speech: "—" } },
            { caption: "Kamera mendeteksi pintu di depan, lalu kursi di kiri.",
              audio: { chime: "Objek dekat (warn)", speech: "Pintu di depan" } },
            { caption: "Seseorang lewat dari kanan—prioritas tinggi.",
              audio: { chime: "Objek dekat (warn)", speech: "Orang di kanan, dekat" } },
            { caption: "Bu Sari menahan tombol Aksi 1 detik untuk meminta ulang.",
              audio: { chime: "Mendengarkan (blip)", speech: "Orang di kanan, dekat" } },
            { caption: "Tiba di tangga — prioritas kritikal.",
              audio: { chime: "Alarm 3×", speech: "Hati-hati, ada turunan di depan" } },
          ]}
          art={["walking", "doorway", "person", "buttonpress", "stairs"]}
        />

        <Scenario
          title="Skenario 2 — Mau makan di kantin"
          mode="Deskripsi" modeColor="var(--info)"
          panels={[
            { caption: "Pencet Mode 1× → masuk Mode Deskripsi (chime 2 nada).",
              audio: { chime: "Mode Deskripsi", speech: "Mode deskripsi" } },
            { caption: "Tekan Aksi → kamera ambil foto, AI memproses.",
              audio: { chime: "Mendengarkan + loop tiap 2 dtk", speech: "—" } },
            { caption: "AI selesai → chord pendek, lalu deskripsi.",
              audio: { chime: "Hasil siap", speech: "Meja kantin dengan piring nasi dan air putih di depan." } },
            { caption: "Bu Sari pencet Aksi 2× → panggil pendamping (notif ke HP guru).",
              audio: { chime: "Konfirmasi", speech: "Pendamping dipanggil" } },
          ]}
          art={["modeswitch", "buttonpress", "table", "phone"]}
        />

        <Scenario
          title="Skenario 3 — Bayar di warung"
          mode="QRIS" modeColor="var(--warn)"
          panels={[
            { caption: "Tekan Mode 2× → masuk Mode QRIS (3 nada).",
              audio: { chime: "Mode QRIS", speech: "Mode bayar" } },
            { caption: "Arahkan kepala ke arah QR — chime panduan saat sudut salah.",
              audio: { chime: "Buzz pendek", speech: "Geser sedikit ke kiri" } },
            { caption: "QR terbaca, AI baca nominal.",
              audio: { chime: "Hasil siap", speech: "Warung Bu Ida, lima belas ribu rupiah." } },
            { caption: "Nominal > 1 juta? minta konfirmasi ulang. (di sini tidak)",
              audio: { chime: "—", speech: "Konfirmasi bayar dengan Aksi" } },
            { caption: "Bu Sari pencet Aksi → lanjut bayar di HP-nya sendiri.",
              audio: { chime: "Konfirmasi", speech: "Siap bayar" } },
          ]}
          art={["modeswitch", "qrscan", "qrok", "confirm", "paid"]}
        />

      </div>
    </div>
  );
};

function Scenario({ title, mode, modeColor, panels, art }) {
  return (
    <section className="card" style={{ padding: "var(--s-5)" }}>
      <header style={{ display: "flex", alignItems: "center", gap: "var(--s-3)",
                       marginBottom: "var(--s-4)", flexWrap: "wrap" }}>
        <h2 style={{ margin: 0, fontSize: "var(--t-xl)" }}>{title}</h2>
        <span className="badge" style={{
          background: modeColor, color: "var(--ink-inverse)", border: "none",
          fontSize: "var(--t-xs)", padding: "4px 12px",
        }}>Mode {mode}</span>
      </header>

      <div style={{
        display: "grid",
        gridTemplateColumns: `repeat(${panels.length}, minmax(0, 1fr))`,
        gap: "var(--s-3)",
      }}>
        {panels.map((p, i) => (
          <Panel key={i} index={i + 1} panel={p} art={art[i]} accent={modeColor} />
        ))}
      </div>
    </section>
  );
}

function Panel({ index, panel, art, accent }) {
  return (
    <article style={{
      border: "1px solid var(--border)",
      borderRadius: "var(--r-md)",
      overflow: "hidden",
      background: "var(--surface)",
      display: "flex", flexDirection: "column",
      minHeight: 340,
    }}>
      {/* art */}
      <div style={{ aspectRatio: "4/3", background: "var(--surface-2)",
                     borderBottom: "1px solid var(--border)", position: "relative" }}>
        <PanelArt name={art} />
        <span style={{
          position: "absolute", top: 8, left: 8,
          background: "var(--ink)", color: "var(--ink-inverse)",
          width: 28, height: 28, borderRadius: "50%",
          display: "grid", placeItems: "center", fontWeight: 700, fontSize: "var(--t-sm)",
        }}>{index}</span>
      </div>

      {/* caption */}
      <div style={{ padding: "var(--s-3)", fontSize: "var(--t-sm)", lineHeight: 1.45,
                     borderBottom: "1px dashed var(--border)" }}>
        {panel.caption}
      </div>

      {/* audio */}
      <div style={{ padding: "var(--s-3)", display: "grid", gap: 6, fontSize: "var(--t-xs)" }}>
        <div style={{ display: "flex", gap: 6, alignItems: "flex-start" }}>
          <span style={{ ...tagLabel, background: "var(--accent-soft)",
                          color: "var(--accent-ink)" }}>Chime</span>
          <span style={{ color: panel.audio.chime === "—" ? "var(--ink-3)" : "var(--ink)" }}>
            {panel.audio.chime}
          </span>
        </div>
        <div style={{ display: "flex", gap: 6, alignItems: "flex-start" }}>
          <span style={{ ...tagLabel, background: "var(--surface-2)" }}>Bicara</span>
          <span style={{ color: panel.audio.speech === "—" ? "var(--ink-3)"
                                                            : "var(--ink)",
                          fontStyle: panel.audio.speech === "—" ? "italic" : "normal" }}>
            {panel.audio.speech === "—" ? "(diam)" : `"${panel.audio.speech}"`}
          </span>
        </div>
      </div>
    </article>
  );
}

const tagLabel = {
  display: "inline-block",
  fontSize: "var(--t-xs)",
  padding: "2px 8px",
  borderRadius: "var(--r-pill)",
  fontWeight: 700,
  flexShrink: 0,
  textTransform: "uppercase",
  letterSpacing: ".05em",
};

/* ─── Tiny vector illustrations for each panel ─────────────────────────── */
function PanelArt({ name }) {
  const W = 200, H = 150;
  const wrap = { position: "absolute", inset: 0 };
  const figure = (children) => (
    <svg viewBox={`0 0 ${W} ${H}`} style={wrap} preserveAspectRatio="xMidYMid meet"
         aria-hidden="true">
      {children}
    </svg>
  );

  switch (name) {
    case "walking":
      return figure(<>
        <rect width={W} height={H} fill="#E8EAE2" />
        <rect y={H-30} width={W} height="30" fill="#a8a08a" />
        <Person x={70} y={H-100} />
        <Glasses x={70} y={H-118} />
      </>);
    case "doorway":
      return figure(<>
        <rect width={W} height={H} fill="#E8EAE2" />
        <rect y={H-30} width={W} height="30" fill="#a8a08a" />
        <rect x={120} y={30} width={50} height={90} fill="#5a3e26" />
        <circle cx={160} cy={75} r="2" fill="#FFD300" />
        <Person x={60} y={H-100} />
        <Glasses x={60} y={H-118} />
        <DetectionBox x={110} y={25} w={70} h={100} label="door 0.88" />
      </>);
    case "person":
      return figure(<>
        <rect width={W} height={H} fill="#E8EAE2" />
        <rect y={H-30} width={W} height="30" fill="#a8a08a" />
        <Person x={60} y={H-100} />
        <Glasses x={60} y={H-118} />
        <Person x={150} y={H-95} color="#5a4030" />
        <DetectionBox x={130} y={45} w={45} h={80} label="person 0.94" />
      </>);
    case "buttonpress":
      return figure(<>
        <rect width={W} height={H} fill="#E8EAE2" />
        <Person x={80} y={H-100} />
        <Glasses x={80} y={H-118} highlight />
        <g transform="translate(120,40)">
          <circle r="22" fill="none" stroke="#FFD300" strokeWidth="3" strokeDasharray="4 4" />
          <path d="M-12 0 L0 0 M-4 -8 L0 0 L-4 8" stroke="#141414" strokeWidth="2.5" fill="none" />
          <text y="40" textAnchor="middle" fontSize="9" fontWeight="700"
                fill="#141414">Tahan</text>
        </g>
      </>);
    case "stairs":
      return figure(<>
        <rect width={W} height={H} fill="#E8EAE2" />
        <g fill="#7a6a55" stroke="#3a3026" strokeWidth="1">
          {[0,1,2,3,4].map(i => (
            <rect key={i} x={100 + i*18} y={H-30 + i*5} width={20} height={5} />
          ))}
        </g>
        <Person x={50} y={H-100} />
        <Glasses x={50} y={H-118} alert />
        <g transform="translate(140, 60)" opacity="0.9">
          <path d="M0 0 L18 24 L-18 24 Z" fill="#B3261E" />
          <text x="0" y="20" textAnchor="middle" fontSize="14" fill="#fff"
                fontWeight="700">!</text>
        </g>
      </>);
    case "modeswitch":
      return figure(<>
        <rect width={W} height={H} fill="#E8EAE2" />
        <Person x={80} y={H-100} />
        <Glasses x={80} y={H-118} highlight />
        <g transform="translate(130,30)">
          <rect x="-14" y="-14" width="28" height="28" rx="4" fill="#FFF" stroke="#141414" strokeWidth="2" />
          <circle cx="-6" cy="0" r="2.5" fill="#141414" />
          <circle cx="0" cy="0"  r="2.5" fill="#141414" />
          <circle cx="6" cy="0"  r="2.5" fill="#141414" />
          <text y="32" textAnchor="middle" fontSize="9" fontWeight="700"
                fill="#141414">Mode</text>
        </g>
      </>);
    case "table":
      return figure(<>
        <rect width={W} height={H} fill="#E8EAE2" />
        <rect x="30" y={H-70} width={140} height={10} fill="#7a6a55" />
        <rect x="40" y={H-60} width="6" height={30} fill="#7a6a55" />
        <rect x="154" y={H-60} width="6" height={30} fill="#7a6a55" />
        <circle cx="80" cy={H-78} r="14" fill="#fff" stroke="#a89880" strokeWidth="2" />
        <circle cx="80" cy={H-78} r="8" fill="#f0e6c2" />
        <rect x="120" y={H-90} width="14" height="20" rx="2" fill="#cce4f4" stroke="#5a85a8" />
      </>);
    case "phone":
      return figure(<>
        <rect width={W} height={H} fill="#E8EAE2" />
        <g transform="translate(100,30)">
          <rect x="-25" y="0" width="50" height="90" rx="6" fill="#141414" />
          <rect x="-22" y="6" width="44" height="76" rx="3" fill="#fff" />
          <rect x="-18" y="14" width="36" height="14" rx="2" fill="#00635D" />
          <text x="0" y="24" fontSize="6" fill="#fff" textAnchor="middle"
                fontWeight="700">Pendamping</text>
          <rect x="-18" y="32" width="36" height="8" rx="2" fill="#EFEDE6" />
          <rect x="-18" y="44" width="36" height="8" rx="2" fill="#EFEDE6" />
        </g>
      </>);
    case "qrscan":
      return figure(<>
        <rect width={W} height={H} fill="#E8EAE2" />
        <Person x={50} y={H-100} />
        <Glasses x={50} y={H-118} />
        <g transform="translate(140,55)">
          <rect x="-22" y="-22" width="44" height="44" fill="#fff" stroke="#141414" strokeWidth="2" />
          {/* qr corners */}
          {[[-22,-22],[22,-22],[-22,22]].map(([cx,cy], i) => (
            <g key={i} transform={`translate(${cx},${cy})`}>
              <rect x="2" y="2" width="10" height="10"
                    fill="none" stroke="#141414" strokeWidth="2"
                    transform={cx<0 && cy<0 ? "" : cx>0 && cy<0 ? "scale(-1,1)" : "scale(1,-1)"} />
            </g>
          ))}
          <g fill="#141414">
            <rect x="-8" y="-8" width="4" height="4" />
            <rect x="0"  y="-8" width="4" height="4" />
            <rect x="-8" y="0" width="4" height="4" />
            <rect x="4"  y="4" width="4" height="4" />
          </g>
        </g>
        {/* misalign indicator */}
        <path d="M100 80 L130 60" stroke="#B3261E" strokeWidth="2" strokeDasharray="4 3" />
      </>);
    case "qrok":
      return figure(<>
        <rect width={W} height={H} fill="#E8EAE2" />
        <Person x={50} y={H-100} />
        <Glasses x={50} y={H-118} alert />
        <DetectionBox x={120} y={35} w={50} h={50} label="QRIS ✓" tone="ok" />
      </>);
    case "confirm":
      return figure(<>
        <rect width={W} height={H} fill="#E8EAE2" />
        <g transform="translate(100,75)">
          <rect x="-50" y="-30" width="100" height="60" rx="8"
                fill="#FCE9C2" stroke="#8A5A00" strokeWidth="2" />
          <text x="0" y="-4" textAnchor="middle" fontSize="11" fontWeight="700" fill="#141414">
            Rp 15.000
          </text>
          <text x="0" y="12" textAnchor="middle" fontSize="9" fill="#5F5F5F">
            Warung Bu Ida
          </text>
        </g>
      </>);
    case "paid":
      return figure(<>
        <rect width={W} height={H} fill="#E8EAE2" />
        <g transform="translate(100,75)">
          <circle r="32" fill="#D5EBD9" stroke="#1F6B3A" strokeWidth="2" />
          <path d="M-12 0 L-3 9 L13 -9" stroke="#1F6B3A" strokeWidth="4" fill="none"
                strokeLinecap="round" strokeLinejoin="round" />
        </g>
      </>);
    default:
      return figure(<rect width={W} height={H} fill="#E8EAE2" />);
  }
}

function Person({ x, y, color = "#3D3D3D" }) {
  return (
    <g transform={`translate(${x},${y})`}>
      <circle cx="0" cy="0" r="10" fill={color} />
      <rect x="-12" y="10" width="24" height="34" rx="6" fill={color} />
      <rect x="-12" y="42" width="9" height="26" fill={color} />
      <rect x="3"   y="42" width="9" height="26" fill={color} />
    </g>
  );
}
function Glasses({ x, y, highlight, alert }) {
  const tone = alert ? "#B3261E" : highlight ? "#FFD300" : "#00635D";
  return (
    <g transform={`translate(${x},${y})`}>
      <circle cx="-5" cy="0" r="4" fill="none" stroke="#141414" strokeWidth="1.2" />
      <circle cx="5"  cy="0" r="4" fill="none" stroke="#141414" strokeWidth="1.2" />
      <line x1="-1" y1="0" x2="1" y2="0" stroke="#141414" strokeWidth="1.2" />
      <rect x="9" y="-3" width="6" height="6" rx="1" fill={tone} />
    </g>
  );
}
function DetectionBox({ x, y, w, h, label, tone = "warn" }) {
  const color = tone === "ok" ? "#1F6B3A" : "#FFD300";
  return (
    <g>
      <rect x={x} y={y} width={w} height={h} fill="none" stroke={color} strokeWidth="2" />
      <rect x={x} y={y - 10} width={Math.max(w, 56)} height="11" fill={color} />
      <text x={x + 3} y={y - 2} fontSize="7" fontWeight="700"
            fill={tone === "ok" ? "#fff" : "#141414"}>{label}</text>
    </g>
  );
}

const kS = { fontSize: "var(--t-xs)", color: "var(--ink-3)",
              textTransform: "uppercase", letterSpacing: ".08em", fontWeight: 700 };

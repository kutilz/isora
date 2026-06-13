/* Companion Dashboard — main view for pendamping (guru SLB / family / volunteer).
   Single-file dashboard component. Renders inside <CompanionDashboard width={...} />.
   Width-aware: <900px collapses to single column mobile layout.
*/

const { useState, useEffect, useRef, useMemo } = React;

/* ─── Mock / demo data ─────────────────────────────────────────────────── */
const DEMO_DEVICE = {
  name: "Kacamata Bu Sari",
  user: "Bu Sari (U3)",
  ip: "192.168.1.42",
  online: true,
  battery: 68,
  wifiSignal: 3,        // 0..4
  wifiName: "SLB-Wifi",
  speakerVolume: 75,
  temperature: 42,
  mode: "explorer",     // explorer | scene | qris
  uptime: "2 jam 14 menit",
};

const DEMO_CAPTION = {
  text: "Orang berdiri di depan kanan, jarak 2 meter",
  time: "baru saja",
  priority: "high",
};

const DEMO_HISTORY = [
  { t: "14:32", icon: "explore", mode: "explorer",  text: "Orang berdiri di depan kanan",            priority: "high" },
  { t: "14:31", icon: "explore", mode: "explorer",  text: "Kursi di depan",                          priority: "high" },
  { t: "14:28", icon: "scene",   mode: "scene",     text: "Ruangan kelas dengan papan tulis hijau, ada 5 kursi tertata rapi menghadap depan.", priority: "info" },
  { t: "14:25", icon: "explore", mode: "explorer",  text: "Tas di kiri",                             priority: "high" },
  { t: "14:22", icon: "warning", mode: "system",    text: "Koneksi WiFi lemah sebentar",             priority: "warn" },
  { t: "14:18", icon: "qris",    mode: "qris",      text: "QRIS: Warung Bu Ida — Rp 15.000",         priority: "info" },
  { t: "14:15", icon: "explore", mode: "explorer",  text: "Motor di kanan, jarak dekat",             priority: "critical" },
  { t: "14:10", icon: "power",   mode: "system",    text: "Device dinyalakan",                       priority: "info" },
];

/* ─── Small atoms ──────────────────────────────────────────────────────── */
function StatusDot({ tone = "ok" }) {
  return <span className={`dot dot--${tone}`} aria-hidden="true" />;
}

function WifiBars({ level = 3, size = 18 }) {
  return (
    <span role="img" aria-label={`Sinyal WiFi ${level} dari 4`}
          style={{ display: "inline-flex", alignItems: "flex-end", gap: 2, height: size }}>
      {[1,2,3,4].map(i => (
        <span key={i} style={{
          width: 4,
          height: (i/4)*size,
          background: i <= level ? "var(--ink)" : "var(--surface-3)",
          borderRadius: 1,
        }} />
      ))}
    </span>
  );
}

function BatteryGauge({ pct = 50, size = 22 }) {
  const tone = pct >= 40 ? "var(--ok)" : pct >= 15 ? "var(--warn)" : "var(--danger)";
  return (
    <span role="img" aria-label={`Baterai ${pct} persen`}
          style={{ display:"inline-flex", alignItems:"center", gap:4 }}>
      <span style={{
        width: size*1.6, height: size,
        border: "2px solid var(--ink)",
        borderRadius: 4,
        position: "relative",
        padding: 2,
      }}>
        <span style={{
          display: "block",
          width: `${pct}%`, height: "100%",
          background: tone,
          borderRadius: 1,
          transition: "width .2s",
        }} />
      </span>
      <span style={{
        width: 4, height: size*0.5,
        background: "var(--ink)",
        borderRadius: "0 2px 2px 0",
      }} />
    </span>
  );
}

/* ─── Big status banner ────────────────────────────────────────────────── */
function StatusBanner({ device }) {
  const online = device.online;
  const tone = online ? "ok" : "danger";
  return (
    <div className="card" role="status" aria-live="polite"
         style={{
           padding: "var(--s-5) var(--s-6)",
           display: "flex",
           alignItems: "center",
           gap: "var(--s-5)",
           background: online ? "var(--ok-soft)" : "var(--danger-soft)",
           borderColor: "transparent",
         }}>
      <div style={{
        width: 56, height: 56,
        borderRadius: "50%",
        background: online ? "var(--ok)" : "var(--danger)",
        color: "var(--ink-inverse)",
        display: "grid", placeItems: "center",
        flexShrink: 0,
      }}>
        <Icon name={online ? "check" : "cross"} size={32} strokeWidth={3} />
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: "var(--t-xs)", color: online ? "var(--ok)" : "var(--danger)",
                      fontWeight: 700, letterSpacing: ".06em", textTransform: "uppercase" }}>
          {online ? "Aktif & Terhubung" : "Tidak terhubung"}
        </div>
        <div style={{ fontSize: "var(--t-xl)", fontWeight: 700, color: "var(--ink)" }}>
          {device.name}
        </div>
        <div style={{ fontSize: "var(--t-sm)", color: "var(--ink-2)" }}>
          {device.user} · {device.ip} · menyala {device.uptime}
        </div>
      </div>
      <button className="btn" aria-label="Buka detail perangkat">
        <Icon name="settings" size={18} /> Detail
      </button>
    </div>
  );
}

/* ─── "What user sees" — camera + caption ──────────────────────────────── */
function LiveView({ device, caption }) {
  return (
    <section className="card" aria-labelledby="live-title"
             style={{ padding: "var(--s-5)", display: "grid", gap: "var(--s-4)" }}>
      <header style={{ display: "flex", alignItems: "center", gap: "var(--s-3)" }}>
        <Icon name="glasses" size={24} />
        <h2 id="live-title" style={{ margin: 0, fontSize: "var(--t-lg)" }}>Yang dilihat pengguna</h2>
        <span className="badge badge--ok" style={{ marginLeft: "auto" }}>
          <StatusDot tone="ok" /> Live
        </span>
      </header>

      {/* Faux camera frame */}
      <div style={{
        background: "#1a1a1a",
        borderRadius: "var(--r-md)",
        aspectRatio: "16/9",
        position: "relative",
        overflow: "hidden",
        border: "1px solid var(--border)",
      }}>
        <svg viewBox="0 0 320 180" width="100%" height="100%" preserveAspectRatio="xMidYMid slice"
             aria-label="Pratinjau kamera dari kacamata pengguna">
          {/* Sky / scene */}
          <defs>
            <linearGradient id="sky" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0" stopColor="#5a7a8e" />
              <stop offset="1" stopColor="#9aa89a" />
            </linearGradient>
            <linearGradient id="floor" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0" stopColor="#7a6a55" />
              <stop offset="1" stopColor="#3a3026" />
            </linearGradient>
          </defs>
          <rect x="0" y="0" width="320" height="110" fill="url(#sky)" />
          <rect x="0" y="110" width="320" height="70" fill="url(#floor)" />
          {/* Wall */}
          <rect x="200" y="40" width="120" height="80" fill="#dcd0b8" opacity="0.85" />
          {/* Door */}
          <rect x="220" y="55" width="35" height="65" fill="#5a3e26" />
          {/* Person silhouette */}
          <g transform="translate(180,60)">
            <circle cx="0" cy="0" r="10" fill="#3a3026" />
            <rect x="-12" y="10" width="24" height="38" rx="8" fill="#5a4030" />
            <rect x="-12" y="46" width="10" height="30" fill="#2a2018" />
            <rect x="2"   y="46" width="10" height="30" fill="#2a2018" />
          </g>

          {/* Detection overlay box */}
          <g>
            <rect x="160" y="48" width="42" height="100"
                  fill="none" stroke="#FFD300" strokeWidth="2" rx="2" />
            <rect x="160" y="38" width="56" height="14" fill="#FFD300" />
            <text x="164" y="49" fontFamily="ui-monospace, monospace"
                  fontSize="10" fill="#000" fontWeight="700">person 0.92</text>
          </g>

          {/* Compass hint */}
          <g transform="translate(16,16)" opacity="0.85">
            <rect x="0" y="0" width="58" height="20" rx="4" fill="rgba(0,0,0,0.55)" />
            <text x="8" y="14" fontFamily="ui-monospace, monospace"
                  fontSize="11" fill="#fff">DEPAN-KANAN</text>
          </g>
        </svg>

        {/* live tag */}
        <div style={{
          position: "absolute", top: 12, right: 12,
          background: "var(--danger)", color: "#fff",
          padding: "4px 10px", borderRadius: "var(--r-pill)",
          fontSize: "var(--t-xs)", fontWeight: 700, letterSpacing: ".08em",
          display: "flex", alignItems: "center", gap: 6,
        }}>
          <span style={{
            width: 8, height: 8, borderRadius: "50%", background: "#fff",
            animation: "pulse 1.5s infinite",
          }} />
          LIVE
        </div>
      </div>

      {/* Last spoken caption */}
      <div aria-live="polite" aria-atomic="true"
           style={{
             padding: "var(--s-4) var(--s-5)",
             background: "var(--surface-2)",
             borderRadius: "var(--r-md)",
             borderLeft: "6px solid var(--accent)",
           }}>
        <div style={{
          fontSize: "var(--t-xs)", textTransform: "uppercase",
          letterSpacing: ".08em", color: "var(--ink-3)",
          fontWeight: 700, marginBottom: 4,
          display: "flex", alignItems: "center", gap: 8,
        }}>
          <Icon name="speaker" size={14} />
          Suara yang pengguna dengar · {caption.time}
        </div>
        <div style={{ fontSize: "var(--t-lg)", fontWeight: 600, color: "var(--ink)" }}>
          "{caption.text}"
        </div>
      </div>

      <div style={{ display: "flex", gap: "var(--s-3)", flexWrap: "wrap" }}>
        <button className="btn">
          <Icon name="refresh" size={18} /> Ulangi suara
        </button>
        <button className="btn">
          <Icon name="play" size={18} /> Tes audio
        </button>
        <button className="btn btn--ghost" style={{ marginLeft: "auto" }}>
          <Icon name="download" size={18} /> Simpan klip
        </button>
      </div>
    </section>
  );
}

/* ─── Mode switcher ────────────────────────────────────────────────────── */
const MODES = [
  { id: "explorer", icon: "explore", name: "Jelajah",   sub: "Sebutkan objek di sekitar (otomatis)", color: "var(--accent)" },
  { id: "scene",    icon: "scene",   name: "Deskripsi", sub: "Jelaskan suasana saat pengguna minta", color: "var(--info)" },
  { id: "qris",     icon: "qris",    name: "Bayar QRIS", sub: "Baca kode QRIS untuk pembayaran",     color: "var(--warn)" },
];

function ModeSwitcher({ active, onChange }) {
  return (
    <section className="card" aria-labelledby="mode-title"
             style={{ padding: "var(--s-5)" }}>
      <h2 id="mode-title" style={{ margin: "0 0 var(--s-2)", fontSize: "var(--t-lg)",
                                   display:"flex", alignItems:"center", gap:8 }}>
        <Icon name="settings" size={22} /> Mode aktif
      </h2>
      <p style={{ margin: "0 0 var(--s-4)", color: "var(--ink-3)", fontSize: "var(--t-sm)" }}>
        Ganti mode dari jarak jauh. Perubahan langsung diumumkan ke pengguna.
      </p>
      <div role="radiogroup" aria-labelledby="mode-title"
           style={{ display: "grid", gap: "var(--s-3)" }}>
        {MODES.map(m => {
          const on = m.id === active;
          return (
            <button
              key={m.id}
              role="radio"
              aria-checked={on}
              onClick={() => onChange(m.id)}
              style={{
                font: "inherit",
                textAlign: "left",
                display: "grid",
                gridTemplateColumns: "auto 1fr auto",
                alignItems: "center",
                gap: "var(--s-4)",
                padding: "var(--s-4) var(--s-5)",
                minHeight: 72,
                background: on ? "var(--accent-soft)" : "var(--surface)",
                border: on ? "3px solid var(--accent)" : "2px solid var(--border)",
                color: "var(--ink)",
                borderRadius: "var(--r-md)",
                cursor: "pointer",
              }}>
              <span style={{
                width: 48, height: 48, borderRadius: "50%",
                background: on ? "var(--accent)" : "var(--surface-2)",
                color: on ? "var(--ink-inverse)" : "var(--ink-2)",
                display: "grid", placeItems: "center",
              }}>
                <Icon name={m.icon} size={26} />
              </span>
              <span>
                <div style={{ fontSize: "var(--t-md)", fontWeight: 700 }}>{m.name}</div>
                <div style={{ fontSize: "var(--t-sm)", color: "var(--ink-3)" }}>{m.sub}</div>
              </span>
              <span aria-hidden="true">
                {on
                  ? <span className="badge badge--accent">AKTIF</span>
                  : <Icon name="arrowRight" size={20} style={{ color: "var(--ink-3)" }} />}
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

/* ─── Volume control ───────────────────────────────────────────────────── */
function VolumeControl({ value, onChange }) {
  const adjust = (d) => onChange(Math.max(0, Math.min(100, value + d)));
  return (
    <section className="card" aria-labelledby="vol-title" style={{ padding: "var(--s-5)" }}>
      <h2 id="vol-title" style={{ margin: 0, fontSize: "var(--t-lg)",
                                   display: "flex", alignItems: "center", gap: 8 }}>
        <Icon name="speaker" size={22} /> Volume suara
        <span className="badge" style={{ marginLeft: "auto" }}>{value}%</span>
      </h2>
      <p style={{ margin: "var(--s-2) 0 var(--s-4)", color: "var(--ink-3)", fontSize: "var(--t-sm)" }}>
        Pastikan pengguna mendengar dengan jelas di lingkungannya.
      </p>
      <div style={{ display: "flex", alignItems: "center", gap: "var(--s-3)" }}>
        <button className="btn btn--icon" aria-label="Kurangi volume 10" onClick={() => adjust(-10)}>
          <Icon name="minus" size={20} />
        </button>
        <div style={{ flex: 1, position: "relative" }}>
          <input
            type="range" min="0" max="100" step="5" value={value}
            aria-label="Volume speaker"
            onChange={(e) => onChange(parseInt(e.target.value))}
            style={{ width: "100%", accentColor: "var(--accent)", height: 32 }}
          />
          <div style={{ display:"flex", justifyContent:"space-between",
                        fontSize:"var(--t-xs)", color:"var(--ink-3)", marginTop: -4 }}>
            <span>Pelan</span><span>Sedang</span><span>Keras</span>
          </div>
        </div>
        <button className="btn btn--icon" aria-label="Tambah volume 10" onClick={() => adjust(10)}>
          <Icon name="plus" size={20} />
        </button>
      </div>
      <button className="btn" style={{ marginTop: "var(--s-4)", width: "100%" }}>
        <Icon name="play" size={18} /> Mainkan suara percobaan
      </button>
    </section>
  );
}

/* ─── Quick status grid ────────────────────────────────────────────────── */
function QuickStatus({ device }) {
  const battTone = device.battery >= 40 ? "ok" : device.battery >= 15 ? "warn" : "danger";
  return (
    <section className="card" aria-labelledby="qs-title" style={{ padding: "var(--s-5)" }}>
      <h2 id="qs-title" style={{ margin: "0 0 var(--s-4)", fontSize: "var(--t-lg)" }}>
        Status singkat
      </h2>
      <ul style={{
        listStyle: "none", padding: 0, margin: 0,
        display: "grid", gap: "var(--s-3)",
        gridTemplateColumns: "repeat(2, 1fr)",
      }}>
        <li style={statRow}>
          <BatteryGauge pct={device.battery} size={22} />
          <div>
            <div style={statKey}>Baterai</div>
            <div style={statVal}>{device.battery}%</div>
          </div>
          <span className={`badge badge--${battTone}`} style={{ marginLeft:"auto" }}>
            {device.battery >= 40 ? "Cukup" : device.battery >= 15 ? "Mulai habis" : "Habis"}
          </span>
        </li>
        <li style={statRow}>
          <WifiBars level={device.wifiSignal} size={22} />
          <div>
            <div style={statKey}>WiFi</div>
            <div style={statVal}>{device.wifiName}</div>
          </div>
          <span className="badge badge--ok" style={{ marginLeft:"auto" }}>Stabil</span>
        </li>
        <li style={statRow}>
          <Icon name="thermometer" size={22} />
          <div>
            <div style={statKey}>Suhu</div>
            <div style={statVal}>{device.temperature}°C</div>
          </div>
          <span className="badge badge--ok" style={{ marginLeft:"auto" }}>Normal</span>
        </li>
        <li style={statRow}>
          <Icon name="cloud" size={22} />
          <div>
            <div style={statKey}>Layanan AI</div>
            <div style={statVal}>OpenAI</div>
          </div>
          <span className="badge badge--ok" style={{ marginLeft:"auto" }}>Aktif</span>
        </li>
      </ul>
    </section>
  );
}
const statRow = {
  display: "flex", alignItems: "center", gap: "var(--s-3)",
  padding: "var(--s-3)",
  background: "var(--surface-2)",
  borderRadius: "var(--r-md)",
};
const statKey = { fontSize: "var(--t-xs)", color: "var(--ink-3)",
                  textTransform: "uppercase", letterSpacing: ".05em", fontWeight: 700 };
const statVal = { fontSize: "var(--t-md)", fontWeight: 600 };

/* ─── Activity timeline ────────────────────────────────────────────────── */
function ActivityFeed({ items }) {
  const [filter, setFilter] = useState("all");
  const filtered = useMemo(() => {
    if (filter === "all") return items;
    return items.filter(i => i.mode === filter);
  }, [items, filter]);

  return (
    <section className="card" aria-labelledby="act-title" style={{ padding: "var(--s-5)" }}>
      <header style={{ display: "flex", alignItems: "center", gap: "var(--s-3)",
                       marginBottom: "var(--s-3)", flexWrap: "wrap" }}>
        <h2 id="act-title" style={{ margin: 0, fontSize: "var(--t-lg)",
                                     display:"flex", alignItems:"center", gap:8 }}>
          <Icon name="history" size={22} /> Riwayat hari ini
        </h2>
        <span className="badge">{filtered.length} kejadian</span>
        <div role="group" aria-label="Filter riwayat" style={{
          marginLeft: "auto", display: "flex", gap: 4,
          background: "var(--surface-2)", padding: 4, borderRadius: "var(--r-pill)",
        }}>
          {[
            ["all", "Semua"],
            ["explorer", "Jelajah"],
            ["scene", "Deskripsi"],
            ["qris", "QRIS"],
            ["system", "Sistem"],
          ].map(([k,l]) => (
            <button key={k} onClick={() => setFilter(k)}
              aria-pressed={filter===k}
              style={{
                font: "inherit",
                padding: "6px 12px",
                border: "none",
                background: filter === k ? "var(--ink)" : "transparent",
                color:      filter === k ? "var(--ink-inverse)" : "var(--ink-2)",
                borderRadius: "var(--r-pill)",
                fontSize: "var(--t-xs)", fontWeight: 600,
                cursor: "pointer",
              }}>
              {l}
            </button>
          ))}
        </div>
      </header>

      <ol style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gap: 0 }}>
        {filtered.map((item, i) => (
          <li key={i} style={{
            display: "grid",
            gridTemplateColumns: "auto auto 1fr auto",
            gap: "var(--s-3)",
            alignItems: "center",
            padding: "var(--s-3) 0",
            borderBottom: i < filtered.length - 1 ? "1px solid var(--border)" : "none",
          }}>
            <span style={{
              fontFamily: "var(--font-mono)",
              fontSize: "var(--t-sm)",
              color: "var(--ink-3)",
              minWidth: 50,
            }}>{item.t}</span>
            <span style={{
              width: 36, height: 36, borderRadius: "50%",
              display: "grid", placeItems: "center",
              background: priColor(item.priority, "soft"),
              color:      priColor(item.priority, "ink"),
            }}>
              <Icon name={item.icon} size={18} />
            </span>
            <span style={{ fontSize: "var(--t-base)", color: "var(--ink)" }}>
              {item.text}
            </span>
            <span className={`badge badge--${priClass(item.priority)}`}>
              {priLabel(item.priority)}
            </span>
          </li>
        ))}
      </ol>

      <div style={{ marginTop: "var(--s-4)", display: "flex", gap: "var(--s-3)" }}>
        <button className="btn"><Icon name="download" size={18} /> Unduh log hari ini (CSV)</button>
        <button className="btn btn--ghost"><Icon name="search" size={18} /> Cari di riwayat</button>
      </div>
    </section>
  );
}
function priColor(p, kind) {
  const map = {
    critical: { soft: "var(--danger-soft)",  ink: "var(--danger)" },
    high:     { soft: "var(--accent-soft)",  ink: "var(--accent-ink)" },
    warn:     { soft: "var(--warn-soft)",    ink: "var(--warn)" },
    info:     { soft: "var(--info-soft)",    ink: "var(--info)" },
  };
  return (map[p] || map.info)[kind];
}
function priClass(p) { return p === "critical" ? "danger" : p === "warn" ? "warn" : p === "info" ? "info" : "accent"; }
function priLabel(p) {
  return { critical: "Penting", high: "Objek", warn: "Peringatan", info: "Info" }[p] || "Info";
}

/* ─── Footer: report problem ───────────────────────────────────────────── */
function ReportFooter() {
  return (
    <section className="card" style={{
      padding: "var(--s-5)",
      background: "var(--surface-2)",
      display: "flex", gap: "var(--s-4)", alignItems: "center", flexWrap: "wrap",
    }}>
      <div style={{ flex: 1, minWidth: 220 }}>
        <div style={{ fontSize: "var(--t-md)", fontWeight: 700 }}>Ada yang aneh?</div>
        <div style={{ color: "var(--ink-3)", fontSize: "var(--t-sm)" }}>
          Lapor ke tim teknis dengan satu klik. Log otomatis dilampirkan.
        </div>
      </div>
      <button className="btn"><Icon name="flag" size={18} /> Lapor masalah</button>
      <button className="btn"><Icon name="bell" size={18} /> Panggil pengguna</button>
      <button className="btn btn--danger"><Icon name="power" size={18} /> Matikan device</button>
    </section>
  );
}

/* ─── A11y top-bar (large text / contrast / reduce motion) ─────────────── */
function A11yBar({ contrast, setContrast, type, setType, motion, setMotion }) {
  return (
    <div role="region" aria-label="Aksesibilitas tampilan"
         style={{
           background: "var(--ink)", color: "var(--ink-inverse)",
           padding: "var(--s-2) var(--s-5)",
           display: "flex", alignItems: "center",
           gap: "var(--s-4)", flexWrap: "wrap",
           fontSize: "var(--t-sm)",
         }}>
      <span style={{ fontWeight: 700 }}>Aksesibilitas:</span>
      <label style={a11yLabel}>
        <input type="checkbox" checked={contrast} onChange={(e) => setContrast(e.target.checked)} />
        <Icon name="contrast" size={16} /> Kontras tinggi
      </label>
      <label style={a11yLabel}>
        <input type="checkbox" checked={type} onChange={(e) => setType(e.target.checked)} />
        <Icon name="text" size={16} /> Teks besar
      </label>
      <label style={a11yLabel}>
        <input type="checkbox" checked={motion} onChange={(e) => setMotion(e.target.checked)} />
        Kurangi animasi
      </label>
      <span style={{ marginLeft: "auto", display: "flex", gap: "var(--s-3)", opacity: .8 }}>
        <span><span className="kbd" style={kbdInverse}>Tab</span> navigasi</span>
        <span><span className="kbd" style={kbdInverse}>1·2·3</span> ganti mode</span>
        <span><span className="kbd" style={kbdInverse}>?</span> bantuan</span>
      </span>
    </div>
  );
}
const a11yLabel = {
  display: "inline-flex", alignItems: "center", gap: 6,
  padding: "4px 10px", borderRadius: "var(--r-pill)",
  background: "rgba(255,255,255,.08)",
  cursor: "pointer",
};
const kbdInverse = {
  background: "rgba(255,255,255,.15)",
  color: "var(--ink-inverse)",
  borderColor: "rgba(255,255,255,.3)",
};

/* ─── Main app shell ───────────────────────────────────────────────────── */
window.CompanionDashboard = function CompanionDashboard({ width = 1280 }) {
  const compact = width < 900;

  const [device, setDevice] = useState(DEMO_DEVICE);
  const [contrast, setContrast] = useState(false);
  const [bigType, setBigType] = useState(false);
  const [motion, setMotion] = useState(false);

  const rootStyle = {
    width: "100%",
    minHeight: "100%",
    background: "var(--bg)",
    color: "var(--ink)",
  };
  const dataAttrs = {
    "data-contrast": contrast ? "high" : "normal",
    "data-type":     bigType  ? "large" : "normal",
    "data-motion":   motion   ? "reduce" : "normal",
  };

  return (
    <div style={rootStyle} {...dataAttrs}>
      <a href="#main" className="skip-link">Lewati ke konten utama</a>

      <A11yBar
        contrast={contrast} setContrast={setContrast}
        type={bigType} setType={setBigType}
        motion={motion} setMotion={setMotion}
      />

      {/* App header */}
      <header style={{
        background: "var(--surface)",
        borderBottom: "1px solid var(--border)",
        padding: "var(--s-4) var(--s-6)",
        display: "flex", alignItems: "center", gap: "var(--s-4)",
        flexWrap: "wrap",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: "var(--s-3)" }}>
          <div style={{
            width: 40, height: 40, borderRadius: 10,
            background: "var(--accent)", color: "var(--ink-inverse)",
            display: "grid", placeItems: "center",
          }}>
            <Icon name="glasses" size={22} />
          </div>
          <div>
            <div style={{ fontWeight: 700, fontSize: "var(--t-md)", lineHeight: 1.1 }}>AuralAI</div>
            <div style={{ fontSize: "var(--t-xs)", color: "var(--ink-3)" }}>Dashboard pendamping</div>
          </div>
        </div>

        <nav aria-label="Menu utama" style={{ display: "flex", gap: 4, marginLeft: "var(--s-6)" }}>
          {[
            ["Beranda", true],
            ["Riwayat", false],
            ["Setup", false],
            ["Bantuan", false],
          ].map(([l, on]) => (
            <a key={l} href="#" aria-current={on ? "page" : undefined}
               style={{
                 padding: "10px 16px",
                 textDecoration: "none",
                 borderRadius: "var(--r-md)",
                 color: on ? "var(--ink)" : "var(--ink-3)",
                 background: on ? "var(--surface-2)" : "transparent",
                 fontWeight: on ? 700 : 500,
                 fontSize: "var(--t-sm)",
               }}>{l}</a>
          ))}
        </nav>

        <div style={{ marginLeft: "auto", display: "flex", gap: "var(--s-3)", alignItems: "center" }}>
          <span className="badge badge--ok" aria-live="polite">
            <StatusDot tone="ok" /> Tersambung
          </span>
          <button className="btn btn--ghost" aria-label="Pengguna saat ini">
            <Icon name="user" size={18} /> {compact ? "" : "Guru Andi"}
          </button>
        </div>
      </header>

      <main id="main" style={{
        padding: compact ? "var(--s-4)" : "var(--s-6)",
        display: "grid", gap: "var(--s-5)",
        maxWidth: 1400, margin: "0 auto",
      }}>
        <StatusBanner device={device} />

        <div style={{
          display: "grid",
          gap: "var(--s-5)",
          gridTemplateColumns: compact ? "1fr" : "minmax(0, 1.4fr) minmax(0, 1fr)",
          alignItems: "start",
        }}>
          {/* Left column */}
          <div style={{ display: "grid", gap: "var(--s-5)" }}>
            <LiveView device={device} caption={DEMO_CAPTION} />
            <ActivityFeed items={DEMO_HISTORY} />
          </div>
          {/* Right column */}
          <div style={{ display: "grid", gap: "var(--s-5)" }}>
            <ModeSwitcher
              active={device.mode}
              onChange={(m) => setDevice(d => ({ ...d, mode: m }))}
            />
            <VolumeControl
              value={device.speakerVolume}
              onChange={(v) => setDevice(d => ({ ...d, speakerVolume: v }))}
            />
            <QuickStatus device={device} />
          </div>
        </div>

        <ReportFooter />

        <footer style={{
          textAlign: "center",
          color: "var(--ink-3)",
          fontSize: "var(--t-xs)",
          padding: "var(--s-4) 0 var(--s-6)",
        }}>
          AuralAI · Sesuai WCAG 2.1 AA · Versi pilot 0.4
          {" · "}
          <a href="#" style={{ color: "var(--ink-3)" }}>Mode lanjutan (admin)</a>
        </footer>
      </main>

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50%      { opacity: .35; }
        }
      `}</style>
    </div>
  );
};

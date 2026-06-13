/* Audio Chime Spec — earcons + haptic + speech priority hierarchy.
   Replaces the all-speech notification system with a chime-first design:
   chime cues are <300ms and instantly recognizable, speech only when info is needed.
*/

window.AudioSpec = function AudioSpec() {
  const chimes = [
    { id: "boot",       name: "AuralAI siap",         shape: "rise",   notes: "C5 → G5",  ms: 320, when: "Selesai boot",                followup: "Suara: 'AuralAI siap digunakan'" },
    { id: "mode-ex",    name: "Mode Jelajah",          shape: "single", notes: "G5",       ms: 120, when: "Pindah ke Jelajah",            followup: "Suara: 'Mode jelajah'" },
    { id: "mode-sc",    name: "Mode Deskripsi",        shape: "two",    notes: "G5–C6",   ms: 200, when: "Pindah ke Deskripsi",          followup: "Suara: 'Mode deskripsi'" },
    { id: "mode-qr",    name: "Mode QRIS",             shape: "three",  notes: "C5–E5–G5",ms: 320, when: "Pindah ke QRIS",                followup: "Suara: 'Mode bayar'" },
    { id: "listen",     name: "Mendengarkan",          shape: "blip",   notes: "E5",      ms: 80,  when: "Aksi ditekan, AI mulai dengar", followup: "—" },
    { id: "thinking",   name: "Sedang memproses",      shape: "loop",   notes: "G4 puls", ms: "tiap 2 dtk", when: "AI Vision menunggu",   followup: "—" },
    { id: "result-ok",  name: "Hasil siap",            shape: "chord",  notes: "C5+G5",   ms: 200, when: "AI selesai jawab",              followup: "Suara: hasil deskripsi" },
    { id: "obstacle",   name: "Ada objek dekat",       shape: "warn",   notes: "A4–C5 cepat", ms: 180, when: "Objek prioritas tinggi",    followup: "Suara: 'Motor di kanan, dekat'" },
    { id: "danger",     name: "Bahaya dekat",          shape: "alarm",  notes: "C5 tiga kali", ms: 360, when: "Objek prioritas kritikal",  followup: "Suara: lokasi + 'hati-hati'" },
    { id: "low-batt",   name: "Baterai 20%",           shape: "drop",   notes: "C5 → E4", ms: 280, when: "Baterai turun ambang",         followup: "Suara: 'Baterai dua puluh persen'" },
    { id: "no-net",     name: "Tidak ada internet",    shape: "drop",   notes: "G4 → D4", ms: 240, when: "Koneksi putus saat butuh AI",   followup: "Suara: 'Sambungan terputus'" },
    { id: "error",      name: "Tidak bisa diproses",   shape: "buzz",   notes: "C4 tumpul", ms: 200, when: "Error AI / scan QRIS gagal",   followup: "Suara: pesan error spesifik" },
    { id: "sleep",      name: "Auto-sleep",            shape: "fade",   notes: "C5 → A4", ms: 600, when: "Idle 2 menit",                 followup: "—" },
  ];

  return (
    <div style={{ padding: "var(--s-6)", background: "var(--bg)", minHeight: "100%" }}>
      <div style={{ maxWidth: 1100, margin: "0 auto", display: "grid", gap: "var(--s-6)" }}>
        <header>
          <div style={kickerA}>Suara sistem · v2</div>
          <h1 style={{ margin: "4px 0 0", fontSize: "var(--t-2xl)" }}>
            Chime, getar, dan suara bicara
          </h1>
          <p style={{ margin: "var(--s-2) 0 0", color: "var(--ink-2)", fontSize: "var(--t-md)",
                      maxWidth: 760 }}>
            Versi lama: setiap event diumumkan dengan kalimat penuh. Hasil: pengguna kewalahan
            di tempat ramai. Versi baru: <strong>chime pendek dulu</strong> (kurang dari 300 ms),
            disusul suara bicara hanya jika ada informasi penting. Pengguna belajar mengenali
            chime dalam ~1 hari.
          </p>
        </header>

        {/* Priority hierarchy */}
        <section className="card" style={{ padding: "var(--s-5)" }}>
          <h2 style={sectionTitleA}>Prioritas audio</h2>
          <p style={{ margin: "var(--s-2) 0 var(--s-4)", color: "var(--ink-3)" }}>
            Saat dua suara mau keluar bersamaan, prioritas lebih tinggi menginterupsi yang
            lebih rendah. Volume juga dinaikkan otomatis untuk level Kritikal.
          </p>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "var(--s-3)" }}>
            <PriorityCard tone="danger" level="P0 Kritikal"
                          color="var(--danger)" softBg="var(--danger-soft)"
                          examples={["Bahaya dekat", "Baterai habis kritis"]}
                          rules="Interupsi semua. Volume +20%. Diulang sampai user respons." />
            <PriorityCard tone="warn" level="P1 Penting"
                          color="var(--warn)" softBg="var(--warn-soft)"
                          examples={["Objek prioritas (motor, mobil)", "Baterai 20%"]}
                          rules="Interupsi P2 & P3. Tidak diulang." />
            <PriorityCard tone="info" level="P2 Info"
                          color="var(--info)" softBg="var(--info-soft)"
                          examples={["Hasil deskripsi", "Mode berganti", "QRIS terbaca"]}
                          rules="Antri di belakang P0/P1. Cooldown 2 dtk per pesan sama." />
            <PriorityCard tone="ok" level="P3 Latar"
                          color="var(--ink-3)" softBg="var(--surface-2)"
                          examples={["Sedang memproses (loop)", "Mendengarkan"]}
                          rules="Tidak menginterupsi. Bisa di-mute terpisah." />
          </div>
        </section>

        {/* Chime library */}
        <section className="card" style={{ padding: "var(--s-5)" }}>
          <h2 style={sectionTitleA}>Pustaka chime</h2>
          <p style={{ margin: "var(--s-2) 0 var(--s-4)", color: "var(--ink-3)" }}>
            Tiap chime punya "bentuk" yang berbeda — naik, turun, satu, dua, tiga nada — supaya
            pengguna kenal tanpa harus dengar kalimat.
          </p>
          <div style={{ overflow: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 760 }}>
              <thead>
                <tr style={{ background: "var(--surface-2)", textAlign: "left" }}>
                  <th style={thA}>Chime</th>
                  <th style={thA}>Bentuk</th>
                  <th style={thA}>Nada · durasi</th>
                  <th style={thA}>Kapan dipakai</th>
                  <th style={thA}>Suara bicara setelahnya</th>
                  <th style={thA}>Putar</th>
                </tr>
              </thead>
              <tbody>
                {chimes.map((c, i) => (
                  <tr key={c.id} style={{
                    borderTop: "1px solid var(--border)",
                    background: i % 2 ? "var(--surface)" : "transparent",
                  }}>
                    <td style={tdA}>
                      <div style={{ fontWeight: 700 }}>{c.name}</div>
                      <div style={{ fontSize: "var(--t-xs)", color: "var(--ink-3)" }}>
                        {c.id}.wav
                      </div>
                    </td>
                    <td style={tdA}>
                      <ChimeShape shape={c.shape} />
                    </td>
                    <td style={tdA}>
                      <div style={{ fontFamily: "var(--font-mono)", fontSize: "var(--t-sm)" }}>{c.notes}</div>
                      <div style={{ fontSize: "var(--t-xs)", color: "var(--ink-3)" }}>{c.ms}{typeof c.ms === "number" ? " ms" : ""}</div>
                    </td>
                    <td style={tdA}>{c.when}</td>
                    <td style={{ ...tdA, color: c.followup === "—" ? "var(--ink-3)" : "var(--ink)" }}>
                      {c.followup}
                    </td>
                    <td style={tdA}>
                      <button className="btn btn--ghost" aria-label={`Putar chime ${c.name}`}>
                        <Icon name="play" size={16} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {/* Haptic + speech */}
        <section style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--s-5)" }}>
          <div className="card" style={{ padding: "var(--s-5)" }}>
            <h2 style={sectionTitleA}>Pola getar</h2>
            <p style={{ margin: "var(--s-2) 0 var(--s-4)", color: "var(--ink-3)" }}>
              Getar dipakai saat suara tidak cocok (di tempat ramai/sunyi total). Diatur via
              dashboard pendamping.
            </p>
            <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gap: "var(--s-3)" }}>
              {[
                ["1 getar pendek",  "Aksi diterima"],
                ["2 getar pendek",  "Mode berganti"],
                ["1 getar panjang", "Error / perhatian"],
                ["3 getar panjang", "Bahaya — interupsi"],
              ].map(([k, v], i) => (
                <li key={i} style={{
                  display: "grid",
                  gridTemplateColumns: "auto 1fr",
                  gap: "var(--s-3)", alignItems: "center",
                  padding: "var(--s-3)",
                  background: "var(--surface-2)",
                  borderRadius: "var(--r-md)",
                }}>
                  <HapticDots pattern={k} />
                  <div>
                    <div style={{ fontWeight: 600, fontSize: "var(--t-sm)" }}>{k}</div>
                    <div style={{ color: "var(--ink-3)", fontSize: "var(--t-sm)" }}>{v}</div>
                  </div>
                </li>
              ))}
            </ul>
          </div>

          <div className="card" style={{ padding: "var(--s-5)" }}>
            <h2 style={sectionTitleA}>Aturan suara bicara</h2>
            <ul style={{ paddingLeft: 18, margin: "var(--s-2) 0 0", display: "grid", gap: "var(--s-2)",
                          color: "var(--ink-2)", lineHeight: 1.55 }}>
              <li>Maksimal 12 kata per kalimat — pengguna harus bisa dengar sambil jalan.</li>
              <li>Format objek: <code>"[Objek] di [arah], jarak [dekat/sedang/jauh]"</code></li>
              <li>Tidak ada kata isian ("eh", "anu", "begini"). Langsung ke informasi.</li>
              <li>Mode Deskripsi maksimal 2 kalimat — sisanya tunggu user minta lagi.</li>
              <li>Bahasa: Indonesia. Angka diucapkan natural ("lima belas ribu", bukan "1-5-0-0-0").</li>
              <li>Volume otomatis naik 20% saat prioritas Kritikal.</li>
              <li>Tidak mengulang pesan sama dalam 2 detik (anti-spam).</li>
            </ul>
          </div>
        </section>
      </div>
    </div>
  );
};

/* ─── Chime shape mini-visualizer ──────────────────────────────────────── */
function ChimeShape({ shape }) {
  const w = 90, h = 36;
  const stroke = "#00635D";
  let path = "";
  let dots = null;
  switch (shape) {
    case "rise":   path = `M5 ${h-6} Q${w/2} 6 ${w-5} 10`; break;
    case "drop":   path = `M5 8 Q${w/2} ${h-4} ${w-5} ${h-6}`; break;
    case "single": dots = [[w/2, h/2]]; break;
    case "two":    dots = [[w*0.35, h-10], [w*0.65, 10]]; break;
    case "three":  dots = [[w*0.2, h-10], [w*0.5, h/2], [w*0.8, 10]]; break;
    case "chord":  dots = [[w/2, 8], [w/2, h-8]]; break;
    case "warn":   path = `M5 ${h/2} L${w*0.25} 10 L${w*0.5} ${h-6} L${w*0.75} 10 L${w-5} ${h/2}`; break;
    case "alarm":  dots = [[w*0.2, h/2], [w*0.5, h/2], [w*0.8, h/2]]; break;
    case "loop":   path = `M5 ${h/2} Q${w*0.25} 8 ${w*0.5} ${h/2} T${w-5} ${h/2}`; break;
    case "blip":   dots = [[w/2, h/2]]; break;
    case "buzz":   path = `M5 ${h/2} L${w*0.25} 8 L${w*0.4} ${h-6} L${w*0.55} 8 L${w*0.7} ${h-6} L${w-5} ${h/2}`; break;
    case "fade":   path = `M5 10 L${w-5} ${h-6}`; break;
    default:       path = `M5 ${h/2} L${w-5} ${h/2}`;
  }
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width={w} height={h}
         aria-hidden="true" style={{ display: "block" }}>
      <line x1="0" y1={h-2} x2={w} y2={h-2} stroke="var(--border)" strokeWidth="1" />
      {path && <path d={path} fill="none" stroke={stroke} strokeWidth="2.5"
                      strokeLinecap="round" strokeLinejoin="round" />}
      {dots && dots.map(([x,y], i) => (
        <circle key={i} cx={x} cy={y} r="4" fill={stroke} />
      ))}
    </svg>
  );
}

/* ─── Haptic pattern dots ──────────────────────────────────────────────── */
function HapticDots({ pattern }) {
  const parts = pattern.split(" ");
  const n = parseInt(parts[0], 10) || 1;
  const long = pattern.includes("panjang");
  return (
    <span aria-hidden="true"
          style={{ display: "inline-flex", alignItems: "center", gap: 4, width: 64 }}>
      {Array.from({ length: n }).map((_, i) => (
        <span key={i} style={{
          width: long ? 22 : 10,
          height: 10,
          borderRadius: 5,
          background: "var(--accent)",
        }} />
      ))}
    </span>
  );
}

/* ─── Priority card ────────────────────────────────────────────────────── */
function PriorityCard({ level, color, softBg, examples, rules }) {
  return (
    <div style={{
      padding: "var(--s-4)",
      borderRadius: "var(--r-md)",
      background: softBg,
      borderLeft: `6px solid ${color}`,
    }}>
      <div style={{ fontSize: "var(--t-xs)", color: color,
                    fontWeight: 700, textTransform: "uppercase", letterSpacing: ".05em" }}>
        {level}
      </div>
      <ul style={{ paddingLeft: 16, margin: "6px 0 8px",
                    fontSize: "var(--t-sm)", lineHeight: 1.45, color: "var(--ink)" }}>
        {examples.map((e, i) => <li key={i}>{e}</li>)}
      </ul>
      <div style={{ fontSize: "var(--t-xs)", color: "var(--ink-3)", fontStyle: "italic" }}>
        {rules}
      </div>
    </div>
  );
}

const sectionTitleA = { margin: 0, fontSize: "var(--t-xl)" };
const kickerA = { fontSize: "var(--t-xs)", color: "var(--ink-3)",
                  textTransform: "uppercase", letterSpacing: ".08em", fontWeight: 700 };
const thA = { padding: "10px 12px", fontWeight: 700, fontSize: "var(--t-xs)",
              textTransform: "uppercase", letterSpacing: ".05em", color: "var(--ink-3)" };
const tdA = { padding: "12px", verticalAlign: "top", fontSize: "var(--t-sm)" };

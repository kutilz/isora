import { useMemo } from "preact/hooks";
import { useManifests, hasChime } from "../../lib/manifests";
import { Icon } from "../atoms/Icon";

const CHIMES = [
  { id: "boot",        name: "AuralAI siap",       shape: "rise",   notes: "C5 → G5",      ms: 320, when: "Selesai boot",                 followup: "Suara: 'AuralAI siap digunakan'" },
  { id: "mode-explorer", name: "Mode Jelajah",     shape: "single", notes: "G5",           ms: 120, when: "Pindah ke Jelajah",             followup: "Suara: 'Mode jelajah'" },
  { id: "mode-scene",  name: "Mode Deskripsi",     shape: "two",    notes: "G5–C6",        ms: 200, when: "Pindah ke Deskripsi",           followup: "Suara: 'Mode deskripsi'" },
  { id: "mode-qris",   name: "Mode QRIS",          shape: "three",  notes: "C5–E5–G5",     ms: 320, when: "Pindah ke QRIS",                followup: "Suara: 'Mode bayar'" },
  { id: "listen",      name: "Mendengarkan",       shape: "blip",   notes: "E5",           ms: 80,  when: "Aksi ditekan, AI mulai dengar", followup: "—" },
  { id: "thinking",    name: "Sedang memproses",   shape: "loop",   notes: "G4 puls",      ms: "tiap 2 dtk", when: "AI Vision menunggu",    followup: "—" },
  { id: "result-ok",   name: "Hasil siap",         shape: "chord",  notes: "C5+G5",        ms: 200, when: "AI selesai jawab",              followup: "Suara: hasil deskripsi" },
  { id: "obstacle",    name: "Ada objek dekat",    shape: "warn",   notes: "A4–C5 cepat",  ms: 180, when: "Objek prioritas tinggi",        followup: "Suara: 'Motor di kanan, dekat'" },
  { id: "danger",      name: "Bahaya dekat",       shape: "alarm",  notes: "C5 tiga kali", ms: 360, when: "Objek prioritas kritikal",      followup: "Suara: lokasi + 'hati-hati'" },
  { id: "low-batt",    name: "Baterai 20%",        shape: "drop",   notes: "C5 → E4",      ms: 280, when: "Baterai turun ambang",          followup: "Suara: 'Baterai dua puluh persen'" },
  { id: "no-net",      name: "Tidak ada internet", shape: "drop",   notes: "G4 → D4",      ms: 240, when: "Koneksi putus saat butuh AI",   followup: "Suara: 'Sambungan terputus'" },
  { id: "error",       name: "Tidak bisa diproses",shape: "buzz",   notes: "C4 tumpul",    ms: 200, when: "Error AI / scan QRIS gagal",    followup: "Suara: pesan error spesifik" },
  { id: "sleep",       name: "Auto-sleep",         shape: "fade",   notes: "C5 → A4",      ms: 600, when: "Idle 2 menit",                  followup: "—" },
];

/**
 * Audio section — port of designs/audio-spec.jsx. The "Putar" column
 * only renders when at least one chime file is present (handoff §2.4).
 */
export function AudioSection() {
  const m = useManifests();
  const anyChime = useMemo(() => CHIMES.some((c) => hasChime(m, c.id)), [m]);

  const playChime = (id: string) => {
    const url = `/audio/chimes/${id}.wav`;
    const a = new Audio(url);
    a.play().catch(() => {
      /* user gesture required on some browsers; ignore */
    });
  };

  const th: any = { padding: "10px 12px", fontWeight: 700, fontSize: "var(--t-xs)",
                     textTransform: "uppercase", letterSpacing: ".05em",
                     color: "var(--ink-3)", textAlign: "left" };
  const td: any = { padding: 12, verticalAlign: "top", fontSize: "var(--t-sm)" };

  return (
    <section
      id="audio"
      style={{ padding: "var(--s-12) var(--s-5)", background: "var(--surface-2)" }}
    >
      <div style={{ maxWidth: 1100, margin: "0 auto" }}>
        <h2 class="section-title">Suara yang kamu akan dengar</h2>
        <p class="section-sub">
          Chime pendek dulu (kurang dari 300 ms), disusul suara bicara hanya
          jika ada informasi penting. Pengguna belajar mengenali chime dalam
          sekitar satu hari.
        </p>

        {/* Priority hierarchy */}
        <div class="grid-4" style={{ marginTop: "var(--s-4)" }}>
          <PriorityCard
            level="P0 Kritikal"
            color="var(--danger)"
            softBg="var(--danger-soft)"
            examples={["Bahaya dekat", "Baterai habis kritis"]}
            rules="Interupsi semua. Volume +20%. Diulang sampai user respons."
          />
          <PriorityCard
            level="P1 Penting"
            color="var(--warn)"
            softBg="var(--warn-soft)"
            examples={["Objek prioritas (motor, mobil)", "Baterai 20%"]}
            rules="Interupsi P2 & P3. Tidak diulang."
          />
          <PriorityCard
            level="P2 Info"
            color="var(--info)"
            softBg="var(--info-soft)"
            examples={["Hasil deskripsi", "Mode berganti", "QRIS terbaca"]}
            rules="Antri di belakang P0/P1. Cooldown 2 dtk per pesan sama."
          />
          <PriorityCard
            level="P3 Latar"
            color="var(--ink-3)"
            softBg="var(--surface)"
            examples={["Sedang memproses (loop)", "Mendengarkan"]}
            rules="Tidak menginterupsi. Bisa di-mute terpisah."
          />
        </div>

        {/* Chime library */}
        <div class="card" style={{ padding: "var(--s-5)", marginTop: "var(--s-8)" }}>
          <h3 style={{ margin: "0 0 var(--s-2)", fontSize: "var(--t-lg)" }}>Pustaka chime</h3>
          {!anyChime && (
            <p
              role="status"
              style={{
                background: "var(--warn-soft)",
                color: "var(--warn)",
                padding: "var(--s-3)",
                borderRadius: "var(--r-sm)",
                fontSize: "var(--t-sm)",
              }}
            >
              Audio sample belum diupload — tombol "Putar" disembunyikan
              sampai file chime tersedia.
            </p>
          )}
          <div style={{ overflow: "auto", marginTop: "var(--s-3)" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 760 }}>
              <thead>
                <tr style={{ background: "var(--surface-2)" }}>
                  <th style={th}>Chime</th>
                  <th style={th}>Bentuk</th>
                  <th style={th}>Nada · durasi</th>
                  <th style={th}>Kapan dipakai</th>
                  <th style={th}>Suara bicara setelahnya</th>
                  {anyChime && <th style={th}>Putar</th>}
                </tr>
              </thead>
              <tbody>
                {CHIMES.map((c, i) => {
                  const canPlay = hasChime(m, c.id);
                  return (
                    <tr
                      key={c.id}
                      style={{
                        borderTop: "1px solid var(--border)",
                        background: i % 2 ? "var(--surface)" : "transparent",
                      }}
                    >
                      <td style={td}>
                        <div style={{ fontWeight: 700 }}>{c.name}</div>
                        <div style={{ fontSize: "var(--t-xs)", color: "var(--ink-3)" }}>
                          {c.id}.wav
                        </div>
                      </td>
                      <td style={td}>
                        <ChimeShape shape={c.shape} />
                      </td>
                      <td style={td}>
                        <div style={{ fontFamily: "var(--font-mono)" }}>{c.notes}</div>
                        <div style={{ fontSize: "var(--t-xs)", color: "var(--ink-3)" }}>
                          {c.ms}
                          {typeof c.ms === "number" ? " ms" : ""}
                        </div>
                      </td>
                      <td style={td}>{c.when}</td>
                      <td style={{ ...td, color: c.followup === "—" ? "var(--ink-3)" : "var(--ink)" }}>
                        {c.followup}
                      </td>
                      {anyChime && (
                        <td style={td}>
                          <button
                            type="button"
                            class="btn btn--ghost"
                            disabled={!canPlay}
                            aria-label={`Putar chime ${c.name}`}
                            title={canPlay ? "Putar" : "Audio belum tersedia"}
                            onClick={() => canPlay && playChime(c.id)}
                          >
                            <Icon name="play" size={16} />
                          </button>
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* Haptic + speech rules */}
        <div class="grid-2" style={{ marginTop: "var(--s-6)" }}>
          <HapticCard />
          <SpeechRulesCard />
        </div>
      </div>
    </section>
  );
}

function PriorityCard({
  level, color, softBg, examples, rules,
}: { level: string; color: string; softBg: string; examples: string[]; rules: string }) {
  return (
    <div
      style={{
        padding: "var(--s-4)",
        borderRadius: "var(--r-md)",
        background: softBg,
        borderLeft: `6px solid ${color}`,
      }}
    >
      <div
        style={{
          fontSize: "var(--t-xs)",
          color,
          fontWeight: 700,
          textTransform: "uppercase",
          letterSpacing: ".05em",
        }}
      >
        {level}
      </div>
      <ul style={{ paddingLeft: 16, margin: "6px 0 8px", fontSize: "var(--t-sm)", lineHeight: 1.45 }}>
        {examples.map((e, i) => <li key={i}>{e}</li>)}
      </ul>
      <div style={{ fontSize: "var(--t-xs)", color: "var(--ink-3)", fontStyle: "italic" }}>
        {rules}
      </div>
    </div>
  );
}

function HapticCard() {
  const items: [string, string][] = [
    ["1 getar pendek", "Aksi diterima"],
    ["2 getar pendek", "Mode berganti"],
    ["1 getar panjang", "Error / perhatian"],
    ["3 getar panjang", "Bahaya — interupsi"],
  ];
  return (
    <div class="card" style={{ padding: "var(--s-5)" }}>
      <h3 style={{ margin: "0 0 var(--s-3)", fontSize: "var(--t-lg)" }}>Pola getar</h3>
      <ul class="stack" style={{ listStyle: "none", padding: 0, margin: 0 }}>
        {items.map(([k, v]) => {
          const n = parseInt(k.split(" ")[0]) || 1;
          const long = k.includes("panjang");
          return (
            <li
              key={k}
              style={{
                display: "grid",
                gridTemplateColumns: "auto 1fr",
                gap: "var(--s-3)",
                alignItems: "center",
                padding: "var(--s-3)",
                background: "var(--surface-2)",
                borderRadius: "var(--r-md)",
              }}
            >
              <span aria-hidden="true" style={{ display: "inline-flex", gap: 4, width: 64 }}>
                {Array.from({ length: n }).map((_, i) => (
                  <span
                    key={i}
                    style={{
                      width: long ? 22 : 10,
                      height: 10,
                      borderRadius: 5,
                      background: "var(--accent)",
                    }}
                  />
                ))}
              </span>
              <div>
                <div style={{ fontWeight: 600, fontSize: "var(--t-sm)" }}>{k}</div>
                <div style={{ color: "var(--ink-3)", fontSize: "var(--t-sm)" }}>{v}</div>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function SpeechRulesCard() {
  return (
    <div class="card" style={{ padding: "var(--s-5)" }}>
      <h3 style={{ margin: "0 0 var(--s-3)", fontSize: "var(--t-lg)" }}>Aturan suara bicara</h3>
      <ul style={{ paddingLeft: 18, margin: 0, display: "grid", gap: "var(--s-2)",
                    color: "var(--ink-2)", lineHeight: 1.55, fontSize: "var(--t-sm)" }}>
        <li>Maksimal 12 kata per kalimat — pengguna harus bisa dengar sambil jalan.</li>
        <li>Format objek: "[Objek] di [arah], jarak [dekat/sedang/jauh]"</li>
        <li>Tidak ada kata isian ("eh", "anu"). Langsung ke informasi.</li>
        <li>Mode Deskripsi maksimal 2 kalimat — sisanya tunggu user minta lagi.</li>
        <li>Bahasa: Indonesia. Angka diucapkan natural ("lima belas ribu").</li>
        <li>Volume otomatis naik 20% saat prioritas Kritikal.</li>
        <li>Tidak mengulang pesan sama dalam 2 detik (anti-spam).</li>
      </ul>
    </div>
  );
}

function ChimeShape({ shape }: { shape: string }) {
  const w = 90, h = 36;
  const stroke = "var(--accent)";
  let path = "";
  let dots: [number, number][] | null = null;
  switch (shape) {
    case "rise":   path = `M5 ${h - 6} Q${w / 2} 6 ${w - 5} 10`; break;
    case "drop":   path = `M5 8 Q${w / 2} ${h - 4} ${w - 5} ${h - 6}`; break;
    case "single": dots = [[w / 2, h / 2]]; break;
    case "two":    dots = [[w * 0.35, h - 10], [w * 0.65, 10]]; break;
    case "three":  dots = [[w * 0.2, h - 10], [w * 0.5, h / 2], [w * 0.8, 10]]; break;
    case "chord":  dots = [[w / 2, 8], [w / 2, h - 8]]; break;
    case "warn":   path = `M5 ${h / 2} L${w * 0.25} 10 L${w * 0.5} ${h - 6} L${w * 0.75} 10 L${w - 5} ${h / 2}`; break;
    case "alarm":  dots = [[w * 0.2, h / 2], [w * 0.5, h / 2], [w * 0.8, h / 2]]; break;
    case "loop":   path = `M5 ${h / 2} Q${w * 0.25} 8 ${w * 0.5} ${h / 2} T${w - 5} ${h / 2}`; break;
    case "blip":   dots = [[w / 2, h / 2]]; break;
    case "buzz":   path = `M5 ${h / 2} L${w * 0.25} 8 L${w * 0.4} ${h - 6} L${w * 0.55} 8 L${w * 0.7} ${h - 6} L${w - 5} ${h / 2}`; break;
    case "fade":   path = `M5 10 L${w - 5} ${h - 6}`; break;
    default:       path = `M5 ${h / 2} L${w - 5} ${h / 2}`;
  }
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width={w} height={h} aria-hidden="true">
      <line x1="0" y1={h - 2} x2={w} y2={h - 2} stroke="var(--border)" stroke-width="1" />
      {path && <path d={path} fill="none" stroke={stroke} stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" />}
      {dots && dots.map(([x, y], i) => <circle key={i} cx={x} cy={y} r="4" fill={stroke} />)}
    </svg>
  );
}

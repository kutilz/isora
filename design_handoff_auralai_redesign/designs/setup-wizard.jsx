/* Setup Wizard — first-time setup for pendamping
   4 steps: Sambungkan → WiFi → API key → Uji.
   Single artboard, not a multi-screen flow — shows all steps with current step highlighted.
*/

window.SetupWizard = function SetupWizard() {
  const [step, setStep] = React.useState(2); // show step 2 (WiFi) as the highlighted one
  const [wifi, setWifi] = React.useState({ ssid: "SLB-Wifi", password: "" });
  const [provider, setProvider] = React.useState("openai");
  const [apiKey, setApiKey] = React.useState("");

  const steps = [
    { n: 1, label: "Hidupkan perangkat",     done: true  },
    { n: 2, label: "Sambungkan WiFi",        done: false },
    { n: 3, label: "API key layanan AI",     done: false },
    { n: 4, label: "Uji & serahkan",         done: false },
  ];

  return (
    <div style={{
      width: "100%", minHeight: "100%",
      background: "var(--bg)",
      padding: "var(--s-6)",
      display: "grid", placeItems: "start center",
    }}>
      <div style={{ maxWidth: 880, width: "100%", display: "grid", gap: "var(--s-5)" }}>

        {/* Header */}
        <header>
          <div style={{ fontSize: "var(--t-xs)", color: "var(--ink-3)",
                        textTransform: "uppercase", letterSpacing: ".08em", fontWeight: 700 }}>
            Persiapan perangkat
          </div>
          <h1 style={{ margin: "4px 0 0", fontSize: "var(--t-2xl)" }}>
            Siapkan kacamata untuk pengguna baru
          </h1>
          <p style={{ margin: "var(--s-2) 0 0", color: "var(--ink-2)", fontSize: "var(--t-md)" }}>
            Empat langkah, sekitar 5 menit. Ikuti urutannya.
          </p>
        </header>

        {/* Progress strip */}
        <ol aria-label="Langkah-langkah setup" style={{
          listStyle: "none", padding: 0, margin: 0,
          display: "grid", gridTemplateColumns: "repeat(4, 1fr)",
          gap: "var(--s-2)",
        }}>
          {steps.map(s => {
            const active = s.n === step;
            const done = s.done;
            return (
              <li key={s.n}>
                <button
                  onClick={() => setStep(s.n)}
                  aria-current={active ? "step" : undefined}
                  style={{
                    font: "inherit",
                    width: "100%", textAlign: "left",
                    padding: "var(--s-3) var(--s-4)",
                    background: active ? "var(--accent-soft)" : done ? "var(--ok-soft)" : "var(--surface)",
                    border: active ? "2px solid var(--accent)" : "2px solid var(--border)",
                    borderRadius: "var(--r-md)",
                    cursor: "pointer",
                    display: "flex", alignItems: "center", gap: "var(--s-3)",
                  }}>
                  <span style={{
                    width: 32, height: 32, borderRadius: "50%",
                    background: done ? "var(--ok)" : active ? "var(--accent)" : "var(--surface-2)",
                    color: (done || active) ? "var(--ink-inverse)" : "var(--ink-2)",
                    display: "grid", placeItems: "center",
                    fontWeight: 700,
                  }}>
                    {done ? <Icon name="check" size={18} strokeWidth={3} /> : s.n}
                  </span>
                  <span>
                    <div style={{ fontSize: "var(--t-xs)", color: "var(--ink-3)", fontWeight: 700,
                                  textTransform:"uppercase", letterSpacing:".05em" }}>
                      Langkah {s.n}
                    </div>
                    <div style={{ fontSize: "var(--t-sm)", fontWeight: 600 }}>{s.label}</div>
                  </span>
                </button>
              </li>
            );
          })}
        </ol>

        {/* Step content */}
        <div className="card" style={{ padding: "var(--s-6)" }}>
          {step === 1 && <Step1 />}
          {step === 2 && <Step2 wifi={wifi} setWifi={setWifi} />}
          {step === 3 && <Step3 provider={provider} setProvider={setProvider}
                                apiKey={apiKey} setApiKey={setApiKey} />}
          {step === 4 && <Step4 />}

          {/* Footer nav */}
          <div style={{
            display: "flex", gap: "var(--s-3)",
            marginTop: "var(--s-6)",
            paddingTop: "var(--s-5)",
            borderTop: "1px solid var(--border)",
          }}>
            <button className="btn" disabled={step === 1}
                    onClick={() => setStep(s => Math.max(1, s - 1))}>
              <Icon name="arrowLeft" size={18} /> Kembali
            </button>
            <button className="btn btn--ghost">Lewati langkah ini</button>
            <span style={{ flex: 1 }} />
            <button className="btn btn--primary btn--lg"
                    onClick={() => setStep(s => Math.min(4, s + 1))}>
              Lanjut langkah {Math.min(4, step + 1)} <Icon name="arrowRight" size={18} />
            </button>
          </div>
        </div>

        {/* Help strip */}
        <div className="card" style={{
          padding: "var(--s-4) var(--s-5)",
          background: "var(--info-soft)", borderColor: "transparent",
          display: "flex", gap: "var(--s-3)", alignItems: "center",
        }}>
          <Icon name="info" size={22} />
          <div style={{ flex: 1 }}>
            <strong>Butuh bantuan?</strong> Buka panduan operator atau hubungi tim teknis.
          </div>
          <button className="btn">Buka panduan</button>
          <button className="btn">Hubungi tim</button>
        </div>
      </div>
    </div>
  );
};

/* ─── STEP 1 — Power on ────────────────────────────────────────────────── */
function Step1() {
  return (
    <>
      <StepHeading n={1} title="Hidupkan kacamata" />
      <p style={stepBody}>
        Tahan tombol <strong>Power</strong> di tangkai kanan selama 2 detik. Kacamata akan berbunyi
        chime singkat lalu mengucapkan <em>"AuralAI siap digunakan"</em>.
      </p>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--s-4)",
                    marginTop: "var(--s-4)" }}>
        <Checkpoint ok label="Lampu indikator hijau menyala" />
        <Checkpoint ok label="Speaker mengucapkan 'AuralAI siap'" />
        <Checkpoint label="Layar dashboard menemukan perangkat di jaringan" />
      </div>
    </>
  );
}

/* ─── STEP 2 — WiFi ────────────────────────────────────────────────────── */
function Step2({ wifi, setWifi }) {
  const nets = [
    { ssid: "SLB-Wifi",      signal: 4, secure: true },
    { ssid: "SLB-Guest",     signal: 3, secure: false },
    { ssid: "RumahBuSari",   signal: 2, secure: true },
    { ssid: "Tetangga-5G",   signal: 1, secure: true },
  ];

  return (
    <>
      <StepHeading n={2} title="Sambungkan ke WiFi" />
      <p style={stepBody}>
        Pilih jaringan yang akan dipakai pengguna sehari-hari. Sinyal sebaiknya 3 dari 4
        bar atau lebih supaya mode Deskripsi dan QRIS tetap cepat.
      </p>

      <div role="radiogroup" aria-label="Pilih jaringan WiFi"
           style={{ marginTop: "var(--s-4)", display: "grid", gap: 4,
                    border: "1px solid var(--border)", borderRadius: "var(--r-md)",
                    overflow: "hidden" }}>
        {nets.map((n, i) => {
          const on = wifi.ssid === n.ssid;
          return (
            <button
              key={n.ssid}
              role="radio"
              aria-checked={on}
              onClick={() => setWifi({ ...wifi, ssid: n.ssid })}
              style={{
                font: "inherit",
                display: "grid",
                gridTemplateColumns: "auto 1fr auto auto",
                gap: "var(--s-3)",
                alignItems: "center",
                padding: "var(--s-4) var(--s-5)",
                background: on ? "var(--accent-soft)" : "var(--surface)",
                border: "none",
                borderTop: i > 0 ? "1px solid var(--border)" : "none",
                cursor: "pointer",
                textAlign: "left",
                minHeight: 60,
              }}>
              <span style={{
                width: 24, height: 24, borderRadius: "50%",
                border: "2px solid var(--ink-2)",
                background: on ? "var(--accent)" : "transparent",
                display: "grid", placeItems: "center",
              }}>
                {on && <span style={{ width: 10, height: 10, borderRadius: "50%",
                                       background: "var(--ink-inverse)" }} />}
              </span>
              <span style={{ fontSize: "var(--t-md)", fontWeight: 600 }}>
                {n.ssid}{n.secure ? "" : " (terbuka)"}
              </span>
              <span aria-label={`Sinyal ${n.signal} dari 4`}>
                <SignalBars level={n.signal} />
              </span>
              {n.secure && <span className="badge" title="Memerlukan kata sandi">Aman</span>}
            </button>
          );
        })}
      </div>

      <div style={{ marginTop: "var(--s-4)" }}>
        <label htmlFor="wifi-pwd" style={fieldLabel}>Kata sandi WiFi</label>
        <input
          id="wifi-pwd" type="password"
          placeholder="Masukkan kata sandi"
          value={wifi.password}
          onChange={(e) => setWifi({ ...wifi, password: e.target.value })}
          style={fieldInput}
        />
        <small style={{ color: "var(--ink-3)", fontSize: "var(--t-sm)" }}>
          Disimpan terenkripsi di perangkat. Tidak akan tampil di dashboard mana pun.
        </small>
      </div>
    </>
  );
}

function SignalBars({ level }) {
  return (
    <span aria-hidden="true" style={{ display: "inline-flex", alignItems: "flex-end", gap: 2, height: 20 }}>
      {[1,2,3,4].map(i => (
        <span key={i} style={{
          width: 4, height: (i/4)*20,
          background: i <= level ? "var(--ink)" : "var(--surface-3)",
          borderRadius: 1,
        }} />
      ))}
    </span>
  );
}

/* ─── STEP 3 — API key ─────────────────────────────────────────────────── */
function Step3({ provider, setProvider, apiKey, setApiKey }) {
  return (
    <>
      <StepHeading n={3} title="Masukkan API key layanan AI" />
      <p style={stepBody}>
        Layanan AI dipakai untuk Mode Deskripsi dan baca QRIS. Mode Jelajah tetap jalan
        meskipun belum ada API key.
      </p>

      <div role="radiogroup" aria-label="Pilih penyedia AI" style={{
        display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "var(--s-3)",
        marginTop: "var(--s-4)",
      }}>
        {[
          ["openai", "OpenAI", "gpt-4o-mini · paling cepat"],
          ["gemini", "Google Gemini", "gemini-1.5-flash · murah"],
          ["claude", "Anthropic Claude", "claude-haiku-4-5 · terbaru"],
        ].map(([id, name, sub]) => {
          const on = provider === id;
          return (
            <button key={id} role="radio" aria-checked={on}
                    onClick={() => setProvider(id)}
                    style={{
                      font: "inherit", padding: "var(--s-4)",
                      textAlign: "left",
                      background: on ? "var(--accent-soft)" : "var(--surface)",
                      border: on ? "3px solid var(--accent)" : "2px solid var(--border)",
                      borderRadius: "var(--r-md)",
                      cursor: "pointer",
                      minHeight: 84,
                    }}>
              <div style={{ fontSize: "var(--t-md)", fontWeight: 700, marginBottom: 2 }}>{name}</div>
              <div style={{ fontSize: "var(--t-xs)", color: "var(--ink-3)" }}>{sub}</div>
            </button>
          );
        })}
      </div>

      <div style={{ marginTop: "var(--s-5)" }}>
        <label htmlFor="api-key" style={fieldLabel}>
          API key {provider === "openai" ? "OpenAI" : provider === "gemini" ? "Google" : "Anthropic"}
        </label>
        <input
          id="api-key" type="password"
          placeholder={provider === "openai" ? "sk-…" : provider === "gemini" ? "AIza…" : "sk-ant-…"}
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          style={fieldInput}
        />
        <small style={{ color: "var(--ink-3)", fontSize: "var(--t-sm)" }}>
          Key dienkripsi sebelum disimpan ke kacamata. Tim teknis bisa <a href="#">membantu
          membuat key</a> kalau belum punya.
        </small>
      </div>

      <div style={{ marginTop: "var(--s-4)", display: "flex", gap: "var(--s-3)", alignItems: "center" }}>
        <button className="btn"><Icon name="link" size={18} /> Tes koneksi</button>
        <span className="badge badge--ok"><StatusDot tone="ok" /> Berhasil · 1.2 detik</span>
      </div>
    </>
  );
}

/* ─── STEP 4 — Verify ─────────────────────────────────────────────────── */
function Step4() {
  const checks = [
    { label: "Speaker terdengar jelas di telinga pengguna",            ok: true  },
    { label: "Mode Jelajah mengucapkan minimal 1 objek dalam 30 detik", ok: true  },
    { label: "Mode Deskripsi menjawab dalam 5 detik",                   ok: true  },
    { label: "Kamera tidak terhalang rambut/topi pengguna",             ok: false },
    { label: "Baterai sudah penuh atau ada power bank cadangan",        ok: false },
  ];
  return (
    <>
      <StepHeading n={4} title="Uji & serahkan ke pengguna" />
      <p style={stepBody}>
        Centang setiap item sambil pengguna mencoba langsung. Jangan serahkan kacamata
        sebelum semua centang hijau.
      </p>
      <ul style={{ listStyle: "none", padding: 0, margin: "var(--s-4) 0", display: "grid", gap: "var(--s-2)" }}>
        {checks.map((c, i) => (
          <li key={i} style={{
            display: "flex", alignItems: "center", gap: "var(--s-3)",
            padding: "var(--s-3) var(--s-4)",
            background: c.ok ? "var(--ok-soft)" : "var(--surface-2)",
            borderRadius: "var(--r-md)",
            borderLeft: `6px solid ${c.ok ? "var(--ok)" : "var(--border-strong)"}`,
          }}>
            <span style={{
              width: 28, height: 28, borderRadius: 6,
              background: c.ok ? "var(--ok)" : "var(--surface)",
              border: c.ok ? "none" : "2px solid var(--border-strong)",
              color: "var(--ink-inverse)",
              display: "grid", placeItems: "center", flexShrink: 0,
            }}>
              {c.ok && <Icon name="check" size={18} strokeWidth={3} />}
            </span>
            <span style={{ fontSize: "var(--t-base)" }}>{c.label}</span>
          </li>
        ))}
      </ul>

      <div style={{
        padding: "var(--s-4)", borderRadius: "var(--r-md)",
        background: "var(--warn-soft)", display: "flex", gap: "var(--s-3)",
      }}>
        <Icon name="warning" size={22} />
        <div>
          <strong>Catat di logbook lapangan</strong>
          <div style={{ color: "var(--ink-2)", marginTop: 2, fontSize: "var(--t-sm)" }}>
            Tanggal, ID pengguna, dan kondisi kacamata saat diserahkan. Data ini dipakai
            untuk laporan IEEE.
          </div>
        </div>
        <button className="btn" style={{ marginLeft: "auto" }}>Buka logbook</button>
      </div>
    </>
  );
}

/* ─── shared bits ──────────────────────────────────────────────────────── */
function StepHeading({ n, title }) {
  return (
    <>
      <div style={{ fontSize: "var(--t-xs)", color: "var(--ink-3)",
                    textTransform: "uppercase", letterSpacing: ".05em", fontWeight: 700 }}>
        Langkah {n} dari 4
      </div>
      <h2 style={{ margin: "4px 0 var(--s-3)", fontSize: "var(--t-xl)" }}>{title}</h2>
    </>
  );
}
function Checkpoint({ label, ok }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: "var(--s-3)",
      padding: "var(--s-3) var(--s-4)",
      borderRadius: "var(--r-md)",
      background: ok ? "var(--ok-soft)" : "var(--surface-2)",
    }}>
      <span style={{
        width: 24, height: 24, borderRadius: "50%",
        background: ok ? "var(--ok)" : "var(--surface)",
        border: ok ? "none" : "2px solid var(--border-strong)",
        color: "var(--ink-inverse)",
        display: "grid", placeItems: "center", flexShrink: 0,
      }}>
        {ok && <Icon name="check" size={14} strokeWidth={3} />}
      </span>
      <span style={{ fontSize: "var(--t-sm)" }}>{label}</span>
    </div>
  );
}
const stepBody  = { margin: 0, color: "var(--ink-2)", fontSize: "var(--t-md)", lineHeight: 1.55 };
const fieldLabel = { display: "block", marginBottom: 6, fontWeight: 600 };
const fieldInput = {
  width: "100%",
  font: "inherit",
  padding: "12px 14px",
  borderRadius: "var(--r-md)",
  border: "2px solid var(--border-strong)",
  background: "var(--surface)",
  color: "var(--ink)",
  fontSize: "var(--t-base)",
  minHeight: 48,
};

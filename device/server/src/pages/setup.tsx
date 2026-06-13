import { render } from "preact";
import { useEffect, useState } from "preact/hooks";
import { A11yBar } from "../components/atoms/A11yBar";
import { SkipLink } from "../components/atoms/SkipLink";
import { Icon } from "../components/atoms/Icon";
import { apiPost, ensureToken } from "../lib/api";
import "../styles/global.css";

/**
 * /setup wizard — handoff §6.2. Four steps:
 *   1. Power on (instructional only)
 *   2. WiFi credentials (manual entry — device WiFi scan endpoint TBD)
 *   3. AI provider + API key (POSTs to /ai-settings/secure)
 *   4. Final checklist → on "Selesai", POSTs setup_completed=true and
 *      navigates to /
 *
 * If the page was opened from /guide's share-link (?audio_mode=…), apply
 * the preference too on finish.
 */

type Provider = "openai" | "gemini" | "claude";

interface State {
  step: 1 | 2 | 3 | 4;
  device_name: string;
  wifi_ssid: string;
  wifi_pw: string;
  provider: Provider;
  api_key: string;
  test_state: "idle" | "testing" | "ok" | "fail";
  test_msg: string;
  checks: boolean[];
  finishing: boolean;
  finish_msg: string;
}

const STEPS: { n: 1 | 2 | 3 | 4; label: string }[] = [
  { n: 1, label: "Hidupkan perangkat" },
  { n: 2, label: "Sambungkan WiFi" },
  { n: 3, label: "API key layanan AI" },
  { n: 4, label: "Uji & serahkan" },
];

function SetupApp() {
  const [s, setS] = useState<State>({
    step: 1,
    device_name: "",
    wifi_ssid: "",
    wifi_pw: "",
    provider: "openai",
    api_key: "",
    test_state: "idle",
    test_msg: "",
    checks: [false, false, false, false, false],
    finishing: false,
    finish_msg: "",
  });

  // ── Read ?audio_mode= from share-link, persist on finish.
  const audioModeFromQuery = (() => {
    try {
      const q = new URLSearchParams(window.location.search).get("audio_mode");
      if (q === "chime" || q === "speech" || q === "both") return q;
    } catch {
      /* ignore */
    }
    return null;
  })();

  // Pre-fill SSID from current /status if device already detected a network.
  useEffect(() => {
    fetch("/status")
      .then((r) => r.json())
      .then((j) => {
        setS((cur) => ({
          ...cur,
          wifi_ssid: j.wifi_ssid && !cur.wifi_ssid ? j.wifi_ssid : cur.wifi_ssid,
          device_name:
            j.device_name && !cur.device_name ? j.device_name : cur.device_name,
        }));
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const goto = (n: 1 | 2 | 3 | 4) => setS((c) => ({ ...c, step: n }));

  const testAi = async () => {
    setS((c) => ({ ...c, test_state: "testing", test_msg: "" }));
    try {
      // Persist key (if any) via the existing /ai-settings save endpoint, then
      // test connection. We don't gate this on key being filled — the device
      // may already have one stored.
      if (s.api_key) {
        await apiPost("/ai-settings", {
          ai_provider: s.provider,
          [`${s.provider}_api_key`]: s.api_key,
        });
      } else {
        await apiPost("/ai-settings", { ai_provider: s.provider });
      }
      const res = await apiPost<{ ok: boolean; message?: string }>(
        "/ai-settings/test",
        {},
      );
      if (res.ok) {
        setS((c) => ({ ...c, test_state: "ok", test_msg: res.message || "Berhasil" }));
      } else {
        setS((c) => ({ ...c, test_state: "fail", test_msg: res.message || "Gagal" }));
      }
    } catch (e: unknown) {
      setS((c) => ({
        ...c,
        test_state: "fail",
        test_msg: e instanceof Error ? e.message : "Gagal",
      }));
    }
  };

  const finish = async () => {
    setS((c) => ({ ...c, finishing: true, finish_msg: "" }));
    try {
      const payload: Record<string, unknown> = { setup_completed: true };
      if (audioModeFromQuery) payload.audio_mode = audioModeFromQuery;
      if (s.device_name.trim()) payload.device_name = s.device_name.trim();
      await apiPost("/config", payload);
      window.location.href = "/";
    } catch (e: unknown) {
      setS((c) => ({
        ...c,
        finishing: false,
        finish_msg: e instanceof Error ? e.message : "Gagal menyimpan",
      }));
    }
  };

  const next = () => {
    if (s.step === 4) {
      finish();
      return;
    }
    goto((s.step + 1) as 1 | 2 | 3 | 4);
  };

  return (
    <div class="app-shell">
      <SkipLink />
      <A11yBar />
      <main
        id="main"
        tabIndex={-1}
        class="page"
        style={{ padding: "var(--s-8) var(--s-5)", maxWidth: 900 }}
      >
        <header>
          <div
            style={{
              fontSize: "var(--t-xs)",
              color: "var(--ink-3)",
              fontWeight: 700,
              letterSpacing: ".08em",
              textTransform: "uppercase",
            }}
          >
            Persiapan perangkat
          </div>
          <h1
            style={{
              margin: "4px 0 var(--s-2)",
              fontSize: "var(--t-2xl)",
            }}
          >
            Siapkan kacamata untuk pengguna baru
          </h1>
          <p style={{ color: "var(--ink-2)", fontSize: "var(--t-md)", margin: 0 }}>
            Empat langkah, sekitar 5 menit. Ikuti urutannya.
          </p>
        </header>

        <ol
          aria-label="Langkah-langkah setup"
          style={{
            listStyle: "none",
            padding: 0,
            margin: "var(--s-5) 0 0",
            display: "grid",
            gridTemplateColumns: "repeat(4, 1fr)",
            gap: "var(--s-2)",
          }}
        >
          {STEPS.map((step) => {
            const active = step.n === s.step;
            const done = step.n < s.step;
            return (
              <li key={step.n}>
                <button
                  type="button"
                  onClick={() => goto(step.n)}
                  aria-current={active ? "step" : undefined}
                  style={{
                    font: "inherit",
                    width: "100%",
                    textAlign: "left",
                    padding: "var(--s-3) var(--s-4)",
                    background: active
                      ? "var(--accent-soft)"
                      : done
                        ? "var(--ok-soft)"
                        : "var(--surface)",
                    border: active
                      ? "2px solid var(--accent)"
                      : "2px solid var(--border)",
                    borderRadius: "var(--r-md)",
                    cursor: "pointer",
                    display: "flex",
                    alignItems: "center",
                    gap: "var(--s-3)",
                    minHeight: "var(--hit)",
                  }}
                >
                  <span
                    style={{
                      width: 32,
                      height: 32,
                      borderRadius: "50%",
                      background: done
                        ? "var(--ok)"
                        : active
                          ? "var(--accent)"
                          : "var(--surface-2)",
                      color:
                        done || active ? "var(--ink-inverse)" : "var(--ink-2)",
                      display: "grid",
                      placeItems: "center",
                      fontWeight: 700,
                    }}
                  >
                    {done ? (
                      <Icon name="check" size={18} strokeWidth={3} />
                    ) : (
                      step.n
                    )}
                  </span>
                  <span>
                    <div
                      style={{
                        fontSize: "var(--t-xs)",
                        color: "var(--ink-3)",
                        fontWeight: 700,
                        textTransform: "uppercase",
                        letterSpacing: ".05em",
                      }}
                    >
                      Langkah {step.n}
                    </div>
                    <div style={{ fontSize: "var(--t-sm)", fontWeight: 600 }}>
                      {step.label}
                    </div>
                  </span>
                </button>
              </li>
            );
          })}
        </ol>

        <div class="card" style={{ padding: "var(--s-6)", marginTop: "var(--s-5)" }}>
          {s.step === 1 && <Step1 />}
          {s.step === 2 && <Step2 s={s} setS={setS} />}
          {s.step === 3 && <Step3 s={s} setS={setS} testAi={testAi} />}
          {s.step === 4 && <Step4 s={s} setS={setS} />}

          <div
            style={{
              display: "flex",
              gap: "var(--s-3)",
              marginTop: "var(--s-6)",
              paddingTop: "var(--s-5)",
              borderTop: "1px solid var(--border)",
              flexWrap: "wrap",
            }}
          >
            <button
              type="button"
              class="btn"
              disabled={s.step === 1}
              onClick={() => goto((s.step - 1) as 1 | 2 | 3 | 4)}
            >
              <Icon name="arrowLeft" size={18} /> Kembali
            </button>
            <button
              type="button"
              class="btn btn--ghost"
              onClick={() =>
                s.step < 4 && goto((s.step + 1) as 1 | 2 | 3 | 4)
              }
              disabled={s.step === 4}
            >
              Lewati langkah ini
            </button>
            <span style={{ flex: 1 }} />
            <button
              type="button"
              class="btn btn--primary btn--lg"
              onClick={next}
              disabled={s.finishing}
            >
              {s.step === 4
                ? s.finishing
                  ? "Menyimpan..."
                  : "Selesai & kembali ke beranda"
                : `Lanjut langkah ${s.step + 1}`}{" "}
              <Icon name="arrowRight" size={18} />
            </button>
          </div>
          {s.finish_msg && (
            <p
              role="alert"
              style={{
                color: "var(--danger)",
                fontSize: "var(--t-sm)",
                marginTop: 12,
              }}
            >
              {s.finish_msg}
            </p>
          )}
        </div>

        <div
          class="card"
          style={{
            padding: "var(--s-4) var(--s-5)",
            background: "var(--info-soft)",
            border: "none",
            display: "flex",
            gap: "var(--s-3)",
            alignItems: "center",
            marginTop: "var(--s-5)",
          }}
        >
          <Icon name="info" size={22} />
          <div style={{ flex: 1 }}>
            <strong>Butuh bantuan?</strong> Buka panduan publik atau hubungi
            tim teknis lewat link di pojok kanan bawah.
          </div>
          <a href="/guide" class="btn">
            Buka panduan
          </a>
        </div>
      </main>
    </div>
  );
}

/* ─── Step 1 — power on ────────────────────────────────────────────────── */

function Step1() {
  return (
    <>
      <StepHeading n={1} title="Hidupkan kacamata" />
      <p style={bodyStyle}>
        Tahan tombol <strong>Power</strong> di tangkai kanan selama 2 detik.
        Kacamata akan berbunyi chime singkat lalu mengucapkan{" "}
        <em>"AuralAI siap digunakan"</em>.
      </p>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: "var(--s-3)",
          marginTop: "var(--s-4)",
        }}
      >
        <Checkpoint label="Lampu indikator hijau menyala" />
        <Checkpoint label="Speaker mengucapkan 'AuralAI siap'" />
        <Checkpoint label="Layar dashboard menemukan perangkat di jaringan" />
      </div>
    </>
  );
}

/* ─── Step 2 — WiFi ────────────────────────────────────────────────────── */

function Step2({ s, setS }: { s: State; setS: (u: (c: State) => State) => void }) {
  return (
    <>
      <StepHeading n={2} title="Sambungkan ke WiFi" />
      <p style={bodyStyle}>
        Masukkan nama jaringan (SSID) dan kata sandi WiFi yang akan dipakai
        pengguna. Sinyal sebaiknya 3 dari 4 bar atau lebih supaya mode
        Deskripsi dan QRIS tetap cepat.
      </p>

      <div style={{ marginTop: "var(--s-4)" }}>
        <label htmlFor="device-name" style={fieldLabel}>
          Nama perangkat (opsional)
        </label>
        <input
          id="device-name"
          type="text"
          autoComplete="off"
          value={s.device_name}
          onInput={(e) =>
            setS((c) => ({
              ...c,
              device_name: (e.currentTarget as HTMLInputElement).value,
            }))
          }
          placeholder="Misal: dapur, kamar-budi"
          style={fieldInput}
        />
        <small style={{ color: "var(--ink-3)", fontSize: "var(--t-sm)" }}>
          Jadi alamat web perangkat:{" "}
          <strong>
            {(s.device_name.trim() || "aural-xxxx")
              .toLowerCase()
              .replace(/[^a-z0-9-]+/g, "-")
              .replace(/-{2,}/g, "-")
              .replace(/^-|-$/g, "")
              .slice(0, 30) || "aural-xxxx"}
            .local:8080
          </strong>
          . Beri nama berbeda untuk tiap unit supaya 5 perangkat tidak bentrok.
          Kosongkan untuk pakai nama otomatis dari nomor perangkat.
        </small>
      </div>

      <div style={{ marginTop: "var(--s-4)" }}>
        <label htmlFor="wifi-ssid" style={fieldLabel}>
          Nama jaringan (SSID)
        </label>
        <input
          id="wifi-ssid"
          type="text"
          autoComplete="off"
          value={s.wifi_ssid}
          onInput={(e) =>
            setS((c) => ({
              ...c,
              wifi_ssid: (e.currentTarget as HTMLInputElement).value,
            }))
          }
          placeholder="Misal: SLB-Wifi"
          style={fieldInput}
        />
      </div>

      <div style={{ marginTop: "var(--s-4)" }}>
        <label htmlFor="wifi-pwd" style={fieldLabel}>
          Kata sandi WiFi
        </label>
        <input
          id="wifi-pwd"
          type="password"
          value={s.wifi_pw}
          onInput={(e) =>
            setS((c) => ({
              ...c,
              wifi_pw: (e.currentTarget as HTMLInputElement).value,
            }))
          }
          placeholder="Masukkan kata sandi"
          style={fieldInput}
        />
        <small style={{ color: "var(--ink-3)", fontSize: "var(--t-sm)" }}>
          Catat dulu nama WiFi dan kata sandinya — kalau perangkat belum
          tersambung, tim teknis akan menyambungkan secara manual saat serah
          terima. Halaman ini akan menyimpan otomatis begitu fitur sambung
          WiFi langsung sudah aktif.
        </small>
      </div>
    </>
  );
}

/* ─── Step 3 — AI provider + key ───────────────────────────────────────── */

function Step3({
  s,
  setS,
  testAi,
}: {
  s: State;
  setS: (u: (c: State) => State) => void;
  testAi: () => Promise<void>;
}) {
  const providers: [Provider, string, string][] = [
    ["openai", "OpenAI", "gpt-4o-mini · paling cepat"],
    ["gemini", "Google Gemini", "gemini-1.5-flash · murah"],
    ["claude", "Anthropic Claude", "claude-haiku-4-5 · terbaru"],
  ];
  const placeholder =
    s.provider === "openai" ? "sk-…" :
    s.provider === "gemini" ? "AIza…" :
    "sk-ant-…";

  return (
    <>
      <StepHeading n={3} title="Masukkan API key layanan AI" />
      <p style={bodyStyle}>
        Layanan AI dipakai untuk Mode Deskripsi dan baca QRIS. Mode Jelajah
        tetap jalan meskipun belum ada API key.
      </p>

      <div
        role="radiogroup"
        aria-label="Pilih penyedia AI"
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, 1fr)",
          gap: "var(--s-3)",
          marginTop: "var(--s-4)",
        }}
      >
        {providers.map(([id, name, sub]) => {
          const on = s.provider === id;
          return (
            <button
              key={id}
              type="button"
              role="radio"
              aria-checked={on}
              onClick={() => setS((c) => ({ ...c, provider: id }))}
              style={{
                font: "inherit",
                padding: "var(--s-4)",
                textAlign: "left",
                background: on ? "var(--accent-soft)" : "var(--surface)",
                border: on
                  ? "3px solid var(--accent)"
                  : "2px solid var(--border)",
                borderRadius: "var(--r-md)",
                cursor: "pointer",
                minHeight: 84,
              }}
            >
              <div
                style={{
                  fontSize: "var(--t-md)",
                  fontWeight: 700,
                  marginBottom: 2,
                }}
              >
                {name}
              </div>
              <div style={{ fontSize: "var(--t-xs)", color: "var(--ink-3)" }}>
                {sub}
              </div>
            </button>
          );
        })}
      </div>

      <div style={{ marginTop: "var(--s-5)" }}>
        <label htmlFor="api-key" style={fieldLabel}>
          API key {providers.find((p) => p[0] === s.provider)?.[1]}
        </label>
        <input
          id="api-key"
          type="password"
          autoComplete="off"
          placeholder={placeholder}
          value={s.api_key}
          onInput={(e) =>
            setS((c) => ({
              ...c,
              api_key: (e.currentTarget as HTMLInputElement).value,
            }))
          }
          style={fieldInput}
        />
        <small style={{ color: "var(--ink-3)", fontSize: "var(--t-sm)" }}>
          Key dienkripsi sebelum disimpan ke kacamata. Kosongkan kalau key
          sebelumnya masih dipakai.
        </small>
      </div>

      <div
        style={{
          marginTop: "var(--s-4)",
          display: "flex",
          gap: "var(--s-3)",
          alignItems: "center",
          flexWrap: "wrap",
        }}
      >
        <button
          type="button"
          class="btn"
          onClick={testAi}
          disabled={s.test_state === "testing"}
        >
          <Icon name="link" size={18} /> Tes koneksi
        </button>
        {s.test_state === "testing" && (
          <span class="badge">Sedang mencoba…</span>
        )}
        {s.test_state === "ok" && (
          <span class="badge badge--ok">✓ {s.test_msg || "Berhasil"}</span>
        )}
        {s.test_state === "fail" && (
          <span class="badge badge--danger">⚠ {s.test_msg || "Gagal"}</span>
        )}
      </div>
    </>
  );
}

/* ─── Step 4 — verify + finish ─────────────────────────────────────────── */

function Step4({
  s,
  setS,
}: {
  s: State;
  setS: (u: (c: State) => State) => void;
}) {
  const labels = [
    "Speaker terdengar jelas di telinga pengguna",
    "Mode Jelajah mengucapkan minimal 1 objek dalam 30 detik",
    "Mode Deskripsi menjawab dalam 5 detik",
    "Kamera tidak terhalang rambut/topi pengguna",
    "Baterai sudah penuh atau ada power bank cadangan",
  ];
  return (
    <>
      <StepHeading n={4} title="Uji & serahkan ke pengguna" />
      <p style={bodyStyle}>
        Centang setiap item sambil pengguna mencoba langsung. Jangan
        serahkan kacamata sebelum semua centang hijau.
      </p>
      <ul
        style={{
          listStyle: "none",
          padding: 0,
          margin: "var(--s-4) 0",
          display: "grid",
          gap: "var(--s-2)",
        }}
      >
        {labels.map((label, i) => {
          const ok = s.checks[i];
          return (
            <li key={i}>
              <label
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "var(--s-3)",
                  padding: "var(--s-3) var(--s-4)",
                  background: ok ? "var(--ok-soft)" : "var(--surface-2)",
                  borderRadius: "var(--r-md)",
                  borderLeft: `6px solid ${
                    ok ? "var(--ok)" : "var(--border-strong)"
                  }`,
                  cursor: "pointer",
                  minHeight: "var(--hit)",
                }}
              >
                <input
                  type="checkbox"
                  checked={ok}
                  onChange={(e) => {
                    const v = (e.currentTarget as HTMLInputElement).checked;
                    setS((c) => {
                      const next = [...c.checks];
                      next[i] = v;
                      return { ...c, checks: next };
                    });
                  }}
                  style={{
                    width: 22,
                    height: 22,
                    accentColor: "var(--ok)",
                    flexShrink: 0,
                  }}
                />
                <span style={{ fontSize: "var(--t-base)" }}>{label}</span>
              </label>
            </li>
          );
        })}
      </ul>
      <div
        style={{
          padding: "var(--s-4)",
          borderRadius: "var(--r-md)",
          background: "var(--warn-soft)",
          display: "flex",
          gap: "var(--s-3)",
        }}
      >
        <Icon name="warning" size={22} />
        <div>
          <strong>Setelah klik "Selesai":</strong>
          <div
            style={{
              color: "var(--ink-2)",
              marginTop: 2,
              fontSize: "var(--t-sm)",
            }}
          >
            Pengaturan tersimpan dan kacamata siap dipakai pengguna. Halaman
            akan kembali ke beranda pendamping. Wizard ini tetap bisa dibuka
            ulang lewat menu Admin kalau perlu.
          </div>
        </div>
      </div>
    </>
  );
}

/* ─── helpers ──────────────────────────────────────────────────────────── */

function StepHeading({ n, title }: { n: number; title: string }) {
  return (
    <>
      <div
        style={{
          fontSize: "var(--t-xs)",
          color: "var(--ink-3)",
          fontWeight: 700,
          textTransform: "uppercase",
          letterSpacing: ".05em",
        }}
      >
        Langkah {n} dari 4
      </div>
      <h2 style={{ margin: "4px 0 var(--s-3)", fontSize: "var(--t-xl)" }}>
        {title}
      </h2>
    </>
  );
}

function Checkpoint({ label }: { label: string }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: "var(--s-3)",
        padding: "var(--s-3) var(--s-4)",
        borderRadius: "var(--r-md)",
        background: "var(--surface-2)",
      }}
    >
      <span
        style={{
          width: 22,
          height: 22,
          borderRadius: "50%",
          background: "var(--surface)",
          border: "2px solid var(--border-strong)",
          flexShrink: 0,
        }}
      />
      <span style={{ fontSize: "var(--t-sm)" }}>{label}</span>
    </div>
  );
}

const bodyStyle: any = {
  margin: 0,
  color: "var(--ink-2)",
  fontSize: "var(--t-md)",
  lineHeight: 1.55,
};
const fieldLabel: any = { display: "block", marginBottom: 6, fontWeight: 600 };
const fieldInput: any = {
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

/* ─── boot ─────────────────────────────────────────────────────────────── */

ensureToken().finally(() => {
  render(<SetupApp />, document.getElementById("root")!);
});

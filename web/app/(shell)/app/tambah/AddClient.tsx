"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import AppBar from "@/components/app/AppBar";
import Notice from "@/components/Notice";
import QrImage from "@/components/QrImage";
import { SettingsGroup, SettingsItem, SettingsLink } from "@/components/app/Settings";
import { ensureSession, type Session } from "@/lib/supabase/session";
import { deviceLabel, deviceSummary, needsSetup, type DeviceRow } from "@/lib/devices";

const CODE_RE = /^[A-Z0-9]{4,8}$/;

type Nearby = { id: string; name: string | null; last_seen: string | null };
type NearbyState =
  | { kind: "loading" }
  | { kind: "unsupported" }
  | { kind: "none" }
  | { kind: "one"; device: Nearby }
  | { kind: "many"; devices: Nearby[] };

type ButtonState = "opening" | "waiting" | "expired" | "failed";

/**
 * What is already linked to this phone — and the escape hatch it exists for.
 *
 * Pairing completes on the DEVICE the instant the button is pressed. If the
 * phone leaves this screen a second later (back, a reload, a mistyped URL, a
 * locked screen), the device is linked and the person is left on a screen that
 * cheerfully waits for a press the device will now refuse with "sudah
 * terhubung" — a loop with no way out. Listing the devices makes that one tap
 * forward instead, and doubles as the way back into a setup left unfinished.
 */
function LinkedDevices() {
  const [devices, setDevices] = useState<DeviceRow[] | null>(null);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const res = await fetch("/api/devices");
        if (!res.ok) return;
        const data = await res.json();
        if (alive) setDevices(data.devices || []);
      } catch {
        /* transient — the interval retries */
      }
    };
    load();
    const timer = setInterval(load, 10_000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);

  if (!devices || devices.length === 0) return null;
  const pending = devices.filter(needsSetup);

  return (
    <SettingsGroup
      title={pending.length > 0 ? "Lanjutkan penyiapan" : "Sudah tertaut"}
      note="Perangkat yang sudah tertaut ke ponsel ini. Kalau tadi kamu sudah menekan tombolnya, perangkatmu ada di sini."
    >
      {devices.map((d) => (
        <SettingsLink
          key={d.id}
          href={needsSetup(d) ? `/app/${d.id}?baru=1` : `/app/${d.id}`}
          lead={
            <span
              className={`dot ${needsSetup(d) ? "dot--warn" : "dot--ok"}`}
              aria-hidden="true"
            />
          }
          label={deviceLabel(d)}
          sub={needsSetup(d) ? "Perlu disiapkan — ketuk untuk lanjut" : deviceSummary(d)}
        />
      ))}
    </SettingsGroup>
  );
}

/**
 * Button pairing — the path that asks the least of the person using it.
 *
 * They are already holding the device, so pressing its ACTION button is both
 * zero effort and a stronger claim to that hardware than sharing a public IP.
 * Unlike the QR (aim a camera you cannot see through) and the spoken code (hear
 * six characters, then type them), it needs no sight and no typing at all.
 *
 * This screen just holds a session open and polls it; the matching happens in
 * /api/pair/confirm when the device reports the press.
 */
function ButtonPair({ onPaired }: { onPaired: (id: string) => void }) {
  const [state, setState] = useState<ButtonState>("opening");
  const [err, setErr] = useState("");
  const sessionId = useRef<string | null>(null);

  const open = useCallback(async () => {
    setErr("");
    setState("opening");
    try {
      const res = await fetch("/api/pair/session", { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Gagal memulai.");
      sessionId.current = data.session_id;
      setState("waiting");
    } catch (e) {
      setErr((e as Error)?.message || "Gagal memulai.");
      setState("failed");
    }
  }, []);

  useEffect(() => {
    open();
  }, [open]);

  useEffect(() => {
    if (state !== "waiting") return;
    let stop = false;
    const timer = setInterval(async () => {
      if (stop || !sessionId.current) return;
      try {
        const res = await fetch(`/api/pair/session?id=${encodeURIComponent(sessionId.current)}`);
        if (!res.ok) return;
        const data = await res.json();
        if (data.status === "paired" && data.device?.id) {
          stop = true;
          clearInterval(timer);
          onPaired(data.device.id);
        } else if (data.status === "expired" || data.status === "gone") {
          stop = true;
          clearInterval(timer);
          setState("expired");
        }
      } catch {
        /* transient — the interval retries */
      }
    }, 2000);
    return () => {
      stop = true;
      clearInterval(timer);
    };
  }, [state, onPaired]);

  return (
    <SettingsGroup
      title="Tekan tombol perangkat"
      note={
        <>
          Berlaku di jaringan mana pun — perangkat tidak harus satu WiFi dengan ponselmu. Kalau
          perangkat menjawab <em>“sudah terhubung”</em>, ia masih tertaut ke ponsel lain: lepaskan
          dulu dari sana, atau lihat daftar di atas.
        </>
      }
    >
      {state === "opening" && <SettingsItem label="Menyiapkan…" />}

      {state === "waiting" && (
        <SettingsItem
          lead={<span className="dot dot--ok" aria-hidden="true" />}
          label="Tekan tombol ACTION sekarang"
          sub="Sekali tekan singkat pada perangkat I-Sora. Halaman ini menunggu — biarkan terbuka."
        />
      )}

      {state === "expired" && (
        <>
          <SettingsItem label="Waktu habis" sub="Tidak ada tombol yang ditekan dalam 3 menit." />
          <div className="srow srow--field">
            <button className="btn btn--primary btn--lg" onClick={open}>
              Mulai lagi
            </button>
          </div>
        </>
      )}

      {state === "failed" && (
        <>
          <SettingsItem label="Gagal memulai" sub={err || undefined} />
          <div className="srow srow--field">
            <button className="btn btn--primary btn--lg" onClick={open}>
              Coba lagi
            </button>
          </div>
        </>
      )}
    </SettingsGroup>
  );
}

/**
 * Automatic path: the device and the phone reach the relay from the same public
 * IP, so the hub can list unclaimed devices "here". A browser cannot scan the
 * LAN itself — HTTPS pages may not touch plain-HTTP local addresses — so this
 * is the only discovery that actually works from a web app.
 *
 * Kept alongside the button because when it does fire it is even quicker: the
 * device is already named on screen and one tap takes it.
 */
function AutoPair({ onPaired }: { onPaired: (id: string) => void }) {
  const [state, setState] = useState<NearbyState>({ kind: "loading" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const scan = useCallback(async () => {
    try {
      const res = await fetch("/api/pair/nearby");
      if (!res.ok) return setState({ kind: "unsupported" });
      const d = await res.json();
      if (!d.supported) return setState({ kind: "unsupported" });
      const list: Nearby[] = d.devices || [];
      if (list.length === 0) setState({ kind: "none" });
      else if (list.length === 1) setState({ kind: "one", device: list[0] });
      else setState({ kind: "many", devices: list });
    } catch {
      /* keep the last known state; the interval retries */
    }
  }, []);

  useEffect(() => {
    scan();
    const timer = setInterval(scan, 4000);
    return () => clearInterval(timer);
  }, [scan]);

  const claim = async (id: string) => {
    setErr("");
    setBusy(true);
    try {
      const res = await fetch("/api/pair/nearby", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ device_id: id }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Gagal menghubungkan.");
      onPaired(data.device.id);
    } catch (e: any) {
      setErr(e?.message || "Gagal menghubungkan.");
      setBusy(false);
    }
  };

  // Silent unless it has something to offer. "Searching…", "none found" and the
  // CGNAT "too many" case are all noise now that the button path — which does
  // not care about any of them — is right above it.
  if (state.kind !== "one") return null;

  return (
    <SettingsGroup title="Atau ketuk saja" note="Perangkat ini terlihat di WiFi yang sama denganmu.">
      <SettingsItem
        lead={<span className="dot dot--ok" aria-hidden="true" />}
        label={deviceLabel(state.device)}
        sub={`Perangkat baru di WiFi ini · ID ${state.device.id.slice(-6)}`}
      />
      <div className="srow srow--field">
        <button
          className="btn btn--primary btn--lg"
          onClick={() => claim(state.device.id)}
          disabled={busy}
        >
          {busy ? "Menghubungkan…" : "Hubungkan perangkat ini"}
        </button>
      </div>

      {err && (
        <div className="srow srow--field">
          <Notice kind="err" style={{ margin: 0 }}>
            {err}
          </Notice>
        </div>
      )}
    </SettingsGroup>
  );
}

/** Camera-QR path: show a signed claim token; the device's own camera reads it. */
function QrPair({ onPaired }: { onPaired: (id: string) => void }) {
  const [value, setValue] = useState("");
  const [err, setErr] = useState("");
  const knownIds = useRef<Set<string> | null>(null);

  const refreshToken = useCallback(async () => {
    try {
      const res = await fetch("/api/pair/qr", { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Gagal membuat kode QR.");
      setValue(data.value);
    } catch (e: any) {
      setErr(e?.message || "Gagal membuat kode QR.");
    }
  }, []);

  useEffect(() => {
    refreshToken();
    const tok = setInterval(refreshToken, 150_000); // refresh before 3-min expiry

    // Baseline of already-owned ids comes from the FIRST successful poll, so a
    // single failed request can never permanently disable detection.
    let inFlight = false;
    const poll = setInterval(async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const r = await fetch("/api/devices");
        if (!r.ok) throw new Error();
        const d = await r.json();
        const ids: string[] = (d.devices || []).map((x: { id: string }) => x.id);
        if (!knownIds.current) {
          knownIds.current = new Set(ids);
          return;
        }
        const freshId = ids.find((id) => !knownIds.current!.has(id));
        if (freshId) {
          clearInterval(poll);
          clearInterval(tok);
          onPaired(freshId);
        }
      } catch {
        /* transient — keep polling */
      } finally {
        inFlight = false;
      }
    }, 2500);

    return () => {
      clearInterval(tok);
      clearInterval(poll);
    };
  }, [refreshToken, onPaired]);

  return (
    <div style={{ display: "grid", gap: "var(--s-4)", justifyItems: "center", textAlign: "center", padding: "var(--s-4)" }}>
      <p style={{ margin: 0, color: "var(--ink-2)" }}>
        Arahkan <strong>kamera perangkat I-Sora</strong> ke kode di bawah — perangkat menautkan
        dirinya sendiri.
      </p>
      <div style={{ background: "#fff", padding: "var(--s-4)", borderRadius: "var(--r-md)" }}>
        {value ? <QrImage value={value} alt="Kode QR untuk dipindai perangkat" /> : <p role="status">Memuat…</p>}
      </div>
      <p className="hint" role="status" style={{ margin: 0 }}>
        Menunggu perangkat memindai… biarkan halaman ini terbuka.
      </p>
      {err && <Notice kind="err">{err}</Notice>}
    </div>
  );
}

/** Spoken-code path: works even when phone and device are on different networks. */
function CodePair({ onPaired, initial = "" }: { onPaired: (id: string) => void; initial?: string }) {
  const [code, setCode] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const valid = CODE_RE.test(code.trim());

  const claim = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    setBusy(true);
    try {
      const res = await fetch("/api/pair/claim", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: code.trim() }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Gagal menghubungkan.");
      onPaired(data.device.id);
    } catch (e: any) {
      setErr(e?.message || "Gagal menghubungkan.");
      setBusy(false);
    }
  };

  return (
    <form onSubmit={claim} style={{ display: "grid", gap: "var(--s-4)", padding: "var(--s-4)" }}>
      <p style={{ margin: 0, color: "var(--ink-2)" }}>
        Perangkat mengucapkan kode singkat. Tekan tombol perangkat <strong>sebentar</strong> untuk
        mendengarnya lagi.
      </p>
      <div className="field">
        <label htmlFor="code">Kode pairing</label>
        <input
          id="code"
          className="input code-input"
          value={code}
          onChange={(e) => setCode(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ""))}
          placeholder="A3F7C1"
          maxLength={8}
          autoComplete="off"
          autoCapitalize="characters"
          aria-describedby="code-hint"
        />
        <span id="code-hint" className="hint">
          4–8 huruf/angka. Kedaluwarsa 10 menit, sekali pakai.
        </span>
      </div>
      {err && <Notice kind="err">{err}</Notice>}
      <button className="btn btn--primary btn--lg" disabled={!valid || busy} type="submit">
        {busy ? "Menghubungkan…" : "Hubungkan"}
      </button>
    </form>
  );
}

export default function AddClient() {
  const router = useRouter();
  // The retired /pair?code=… deep link still forwards here (see app/pair).
  const initialCode = (useSearchParams().get("code") || "").toUpperCase();
  // Pairing writes ownership, so it needs an identity — but the user never has
  // to make one: ensureSession() mints an anonymous Supabase user silently.
  const [session, setSession] = useState<Session | null>(null);

  useEffect(() => {
    let alive = true;
    ensureSession().then((s) => alive && setSession(s));
    return () => {
      alive = false;
    };
  }, []);

  // replace, not push: after pairing, Back must go to the device list — not to
  // this screen, which would sit there waiting for a press the device will now
  // refuse because it is already paired.
  const onPaired = useCallback(
    (id: string) => router.replace(`/app/${id}?baru=1`),
    [router]
  );

  if (!session) {
    return (
      <>
        <AppBar title="Tambah perangkat" back="/app" />
        <div className="app-body" role="status">
          <SettingsGroup>
            <SettingsItem label="Menyiapkan…" />
          </SettingsGroup>
        </div>
      </>
    );
  }

  if (session.kind === "none") {
    return (
      <>
        <AppBar title="Tambah perangkat" back="/app" />
        <div className="app-body">
          <SettingsGroup
            title="Belum bisa menghubungkan"
            note="Pairing butuh koneksi ke relay I-Sora. Perangkatmu sendiri tetap berfungsi penuh tanpa ini."
          >
            <SettingsItem label="Relay tidak bisa dihubungi" sub={session.reason} />
            <SettingsLink href="/docs/masalah-umum" label="Masalah umum" />
          </SettingsGroup>
        </div>
      </>
    );
  }

  return (
    <>
      <AppBar title="Tambah perangkat" back="/app" />
      <div className="app-body">
        <LinkedDevices />
        <ButtonPair onPaired={onPaired} />
        <AutoPair onPaired={onPaired} />

        <SettingsGroup
          title="Cara lain"
          note="Hampir tidak pernah perlu. Pakai ini kalau tombol perangkat rusak, atau kalau perangkat belum bisa menjangkau internet sama sekali."
        >
          <details>
            <summary className="srow">
              <span className="srow__main">
                <span className="srow__label">Pindai QR dengan kamera perangkat</span>
                <span className="srow__sub">Tanpa mengetik — perangkat yang membaca layarmu</span>
              </span>
            </summary>
            <QrPair onPaired={onPaired} />
          </details>

          <details open={!!initialCode}>
            <summary className="srow">
              <span className="srow__main">
                <span className="srow__label">Ketik kode suara</span>
                <span className="srow__sub">Kode yang diucapkan perangkat</span>
              </span>
            </summary>
            <CodePair onPaired={onPaired} initial={initialCode} />
          </details>
        </SettingsGroup>
      </div>
    </>
  );
}

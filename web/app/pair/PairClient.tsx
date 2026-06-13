"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import DeviceConfigForm, { type Device } from "@/components/DeviceConfigForm";
import QrImage from "@/components/QrImage";

const CODE_RE = /^[A-Z0-9]{4,8}$/;

async function loadDevice(id: string): Promise<Device | null> {
  const res = await fetch(`/api/devices/${id}`);
  if (!res.ok) return null;
  const data = await res.json();
  return { id: data.device.id, name: data.device.name, pubkey: data.device.pubkey };
}

/** Camera-QR pairing: show a QR, watch for a device to claim itself. */
function PairQr({ onClaimed }: { onClaimed: (d: Device) => void }) {
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
    // snapshot devices already owned so we can detect the newly paired one
    fetch("/api/devices")
      .then((r) => (r.ok ? r.json() : { devices: [] }))
      .then((d) => {
        knownIds.current = new Set((d.devices || []).map((x: any) => x.id));
      });
    refreshToken();
    const tok = setInterval(refreshToken, 150_000); // refresh before 3-min expiry

    const poll = setInterval(async () => {
      if (!knownIds.current) return;
      const r = await fetch("/api/devices");
      if (!r.ok) return;
      const d = await r.json();
      const fresh = (d.devices || []).find((x: any) => !knownIds.current!.has(x.id));
      if (fresh) {
        const dev = await loadDevice(fresh.id);
        if (dev) {
          clearInterval(poll);
          clearInterval(tok);
          onClaimed(dev);
        }
      }
    }, 2500);

    return () => {
      clearInterval(tok);
      clearInterval(poll);
    };
  }, [refreshToken, onClaimed]);

  return (
    <div style={{ display: "grid", gap: "var(--s-4)", justifyItems: "center", textAlign: "center" }}>
      <p style={{ margin: 0, color: "var(--ink-2)" }}>
        Arahkan <strong>kamera perangkat I-Sora</strong> ke kode QR di bawah. Perangkat akan
        menautkan dirinya secara otomatis.
      </p>
      <div className="card" style={{ padding: "var(--s-4)", background: "#fff" }}>
        {value ? <QrImage value={value} alt="Kode QR untuk dipindai perangkat" /> : <p>Memuat…</p>}
      </div>
      <p className="hint" style={{ margin: 0 }}>
        Menunggu perangkat memindai… biarkan halaman ini terbuka.
      </p>
      {err && <div className="notice notice--err">{err}</div>}
    </div>
  );
}

export default function PairClient() {
  const params = useSearchParams();
  const router = useRouter();

  const [authChecked, setAuthChecked] = useState(false);
  const [signedIn, setSignedIn] = useState(false);
  const [tab, setTab] = useState<"qr" | "code">("qr");

  const [code, setCode] = useState((params.get("code") || "").toUpperCase());
  const [device, setDevice] = useState<Device | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [done, setDone] = useState(false);

  useEffect(() => {
    createClient()
      .auth.getUser()
      .then(({ data }) => {
        setSignedIn(!!data.user);
        setAuthChecked(true);
      });
  }, []);

  // a code in the URL (from the typed-code QR deep link) jumps to the code tab
  useEffect(() => {
    if (params.get("code")) setTab("code");
  }, [params]);

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
      setDevice(data.device);
    } catch (e: any) {
      setErr(e?.message || "Gagal menghubungkan.");
    } finally {
      setBusy(false);
    }
  };

  if (!authChecked) return <div className="container section">Memuat…</div>;

  if (!signedIn) {
    const next = `/pair${code ? `?code=${encodeURIComponent(code)}` : ""}`;
    return (
      <div className="container section" style={{ maxWidth: 460 }}>
        <h1 style={{ fontSize: "var(--t-2xl)", letterSpacing: "-.02em" }}>Hubungkan perangkat</h1>
        <p className="sub">Masuk dulu agar perangkat tertaut ke akunmu.</p>
        <Link href={`/login?next=${encodeURIComponent(next)}`} className="btn btn--primary btn--lg">
          Masuk untuk melanjutkan
        </Link>
      </div>
    );
  }

  if (done) {
    return (
      <div className="container section" style={{ maxWidth: 560 }}>
        <h1 style={{ fontSize: "var(--t-2xl)", letterSpacing: "-.02em" }}>Berhasil terhubung 🎉</h1>
        <div className="notice notice--ok" style={{ marginBottom: "var(--s-6)" }}>
          Pengaturan terkirim ke perangkat. Perangkat akan mengucapkan “Perangkat sudah terhubung.”
        </div>
        <button className="btn btn--primary btn--lg" onClick={() => router.push("/dashboard")}>
          Lihat perangkat saya
        </button>
      </div>
    );
  }

  if (device) {
    return (
      <div className="container section" style={{ maxWidth: 560 }}>
        <h1 style={{ fontSize: "var(--t-2xl)", letterSpacing: "-.02em" }}>Atur perangkat</h1>
        <p className="sub">Perangkat tertaut. Pilih layanan AI dan preferensi suara.</p>
        <div className="card">
          <DeviceConfigForm device={device} onDone={() => setDone(true)} />
        </div>
      </div>
    );
  }

  return (
    <div className="container section" style={{ maxWidth: 560 }}>
      <h1 style={{ fontSize: "var(--t-2xl)", letterSpacing: "-.02em" }}>Hubungkan perangkat</h1>
      <p className="sub">Dua cara — pilih yang paling mudah.</p>

      <div role="tablist" aria-label="Cara menghubungkan" style={{ display: "flex", gap: "var(--s-2)", marginBottom: "var(--s-5)" }}>
        <button role="tab" aria-selected={tab === "qr"}
          className={tab === "qr" ? "btn btn--primary" : "btn"} onClick={() => setTab("qr")}>
          Pindai QR (kamera)
        </button>
        <button role="tab" aria-selected={tab === "code"}
          className={tab === "code" ? "btn btn--primary" : "btn"} onClick={() => setTab("code")}>
          Ketik kode suara
        </button>
      </div>

      {tab === "qr" ? (
        <div className="card">
          <PairQr onClaimed={setDevice} />
        </div>
      ) : (
        <form onSubmit={claim} className="card" style={{ display: "grid", gap: "var(--s-4)" }}>
          <p style={{ margin: 0, color: "var(--ink-2)" }}>
            Masukkan kode singkat yang diucapkan perangkat. Tekan tombol perangkat
            <strong> sebentar</strong> untuk mendengar ulang kode.
          </p>
          <div className="field">
            <label htmlFor="code">Kode pairing</label>
            <input id="code" className="input code-input" value={code}
              onChange={(e) => setCode(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ""))}
              placeholder="A3F7C1" maxLength={8} autoComplete="off" autoCapitalize="characters"
              aria-describedby="code-hint" />
            <span id="code-hint" className="hint">4–8 huruf/angka. Kedaluwarsa 10 menit, sekali pakai.</span>
          </div>
          {err && <div className="notice notice--err">{err}</div>}
          <button className="btn btn--primary btn--lg" disabled={!valid || busy} type="submit">
            {busy ? "Menghubungkan…" : "Hubungkan"}
          </button>
        </form>
      )}
    </div>
  );
}

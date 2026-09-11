"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import DeviceConfigForm, { type Device } from "@/components/DeviceConfigForm";
import Notice from "@/components/Notice";

type DeviceRow = {
  id: string;
  name: string | null;
  fw_version: string | null;
  status: Record<string, any> | null;
  last_seen: string | null;
};

const ONLINE_WINDOW_MS = 90_000;

function isOnline(lastSeen: string | null): boolean {
  if (!lastSeen) return false;
  return Date.now() - new Date(lastSeen).getTime() < ONLINE_WINDOW_MS;
}

function lastSeenText(lastSeen: string): string {
  const mins = Math.max(1, Math.round((Date.now() - new Date(lastSeen).getTime()) / 60_000));
  if (mins < 60) return `${mins} menit lalu`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours} jam lalu`;
  return `${Math.round(hours / 24)} hari lalu`;
}

function DeviceCard({ d }: { d: DeviceRow }) {
  const online = isOnline(d.last_seen);
  const [editing, setEditing] = useState(false);
  const [full, setFull] = useState<Device | null>(null);
  const [loading, setLoading] = useState(false);

  const openEdit = async () => {
    setEditing(true);
    if (full) return;
    setLoading(true);
    try {
      const res = await fetch(`/api/devices/${d.id}`);
      const data = await res.json();
      if (res.ok) setFull({ id: data.device.id, name: data.device.name, pubkey: data.device.pubkey });
    } catch {
      // full stays null → the error notice below covers it
    } finally {
      setLoading(false);
    }
  };

  const s = d.status || {};
  const localUrl =
    typeof s.local_url === "string" && s.local_url.startsWith("http") ? s.local_url : null;

  return (
    <div className="card" style={{ display: "grid", gap: "var(--s-3)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "var(--s-3)" }}>
        <span className={`dot ${online ? "dot--ok" : "dot--danger"}`} aria-hidden="true" />
        <strong style={{ fontSize: "var(--t-lg)" }}>{d.name || d.id}</strong>
        <span className="badge" style={{ marginLeft: "auto" }}>
          {online ? "Terhubung" : "Terputus"}
        </span>
      </div>

      {!online && d.last_seen && (
        <p style={{ margin: 0, color: "var(--ink-3)", fontSize: "var(--t-sm)" }}>
          Terakhir terlihat {lastSeenText(d.last_seen)}.
        </p>
      )}

      {s.data_collection_mode && (
        <Notice kind="warn" alert style={{ margin: 0 }}>
          <strong>Mode Ambil Data aktif</strong>
          {s.capturing ? " — sedang merekam" : " — siaga"}
          {typeof s.capture_count === "number" && ` · ${s.capture_count} foto`}. Fitur asistif
          perangkat nonaktif selama mode ini. Matikan lewat{" "}
          {localUrl ? (
            <a href={`${localUrl}/collect`}>halaman Ambil Data perangkat</a>
          ) : (
            "halaman /collect di perangkat"
          )}
          .
        </Notice>
      )}

      <div style={{ color: "var(--ink-2)", display: "flex", gap: "var(--s-5)", flexWrap: "wrap" }}>
        {s.mode && <span>Mode: <strong>{s.mode}</strong></span>}
        {typeof s.battery === "number" && <span>Baterai: <strong>{s.battery}%</strong></span>}
        {s.wifi && <span>WiFi: <strong>{s.wifi}</strong></span>}
        {d.fw_version && <span style={{ color: "var(--ink-3)" }}>v{d.fw_version}</span>}
      </div>

      {online && localUrl && (
        <p style={{ margin: 0 }}>
          <a href={`${localUrl}/buttons`}>Kendali tombol perangkat</a>{" "}
          <span style={{ color: "var(--ink-3)", fontSize: "var(--t-sm)" }}>
            (buka dari WiFi yang sama dengan perangkat)
          </span>
        </p>
      )}

      {!editing ? (
        <button className="btn" onClick={openEdit} style={{ justifySelf: "start" }}>
          Atur perangkat
        </button>
      ) : loading ? (
        <p role="status" style={{ margin: 0, color: "var(--ink-3)" }}>Memuat…</p>
      ) : full ? (
        <div style={{ borderTop: "1px solid var(--border)", paddingTop: "var(--s-4)", display: "grid", gap: "var(--s-4)" }}>
          <DeviceConfigForm device={full} submitLabel="Kirim pengaturan ke perangkat" />
          <button className="btn" onClick={() => setEditing(false)} style={{ justifySelf: "start" }}>
            Tutup
          </button>
        </div>
      ) : (
        <div style={{ display: "grid", gap: "var(--s-3)" }}>
          <Notice kind="err" style={{ margin: 0 }}>Gagal memuat detail perangkat.</Notice>
          <button className="btn" onClick={openEdit} style={{ justifySelf: "start" }}>
            Coba lagi
          </button>
        </div>
      )}
    </div>
  );
}

export default function DashboardClient() {
  const [authChecked, setAuthChecked] = useState(false);
  const [signedIn, setSignedIn] = useState<boolean | null>(null);
  const [devices, setDevices] = useState<DeviceRow[] | null>(null);
  const [err, setErr] = useState("");

  const load = useCallback(async (): Promise<"ok" | "unauth" | "fail"> => {
    try {
      const res = await fetch("/api/devices");
      if (res.status === 401) {
        setSignedIn(false);
        return "unauth";
      }
      const data = await res.json();
      if (!res.ok) {
        setErr(data.error || "Gagal memuat perangkat.");
      } else {
        setDevices(data.devices);
        setErr(""); // clear stale error once we recover
      }
      setSignedIn(true);
      return "ok";
    } catch {
      // network down / server unreachable — keep the page alive, interval retries
      setErr("Tidak bisa terhubung ke server — periksa koneksi internetmu.");
      return "fail";
    } finally {
      setAuthChecked(true);
    }
  }, []);

  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | null = null;
    const tick = async () => {
      if ((await load()) === "unauth" && timer) {
        clearInterval(timer); // don't keep polling the sign-in screen
        timer = null;
      }
    };
    tick();
    timer = setInterval(tick, 30_000); // refresh status periodically
    return () => {
      if (timer) clearInterval(timer);
    };
  }, [load]);

  if (!authChecked) {
    return <div className="container section" role="status">Memuat…</div>;
  }

  if (signedIn === false) {
    return (
      <div className="container section" style={{ maxWidth: 460 }}>
        <h1 style={{ fontSize: "var(--t-2xl)", letterSpacing: "-.02em" }}>Perangkat saya</h1>
        <p className="sub">Masuk untuk melihat perangkatmu.</p>
        <Link href="/login?next=/dashboard" className="btn btn--primary btn--lg">Masuk</Link>
      </div>
    );
  }

  if (signedIn === null) {
    // network failed before we ever learned the auth state
    return (
      <div className="container section" style={{ maxWidth: 460 }}>
        <h1 style={{ fontSize: "var(--t-2xl)", letterSpacing: "-.02em" }}>Perangkat saya</h1>
        <Notice kind="err">{err || "Tidak bisa terhubung ke server — periksa koneksi internetmu."}</Notice>
        <button className="btn" style={{ marginTop: "var(--s-4)" }} onClick={() => load()}>
          Coba lagi
        </button>
      </div>
    );
  }

  return (
    <div className="container section" style={{ maxWidth: 720 }}>
      <div style={{ display: "flex", alignItems: "center", gap: "var(--s-4)" }}>
        <h1 style={{ fontSize: "var(--t-2xl)", letterSpacing: "-.02em", margin: 0 }}>Perangkat saya</h1>
        <form action="/auth/signout" method="post" style={{ marginLeft: "auto" }}>
          <button className="btn" type="submit">Keluar</button>
        </form>
      </div>

      {err && <Notice kind="err" style={{ marginTop: "var(--s-4)" }}>{err}</Notice>}

      {devices && devices.length === 0 && (
        <div className="card" style={{ marginTop: "var(--s-6)" }}>
          <p style={{ margin: 0 }}>
            Belum ada perangkat. <Link href="/pair">Hubungkan perangkat</Link> dengan kode yang diucapkannya.
          </p>
        </div>
      )}

      <div className="grid" style={{ marginTop: "var(--s-6)" }}>
        {devices?.map((d) => <DeviceCard key={d.id} d={d} />)}
      </div>
    </div>
  );
}

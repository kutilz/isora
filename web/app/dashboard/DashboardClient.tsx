"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import DeviceConfigForm, { type Device } from "@/components/DeviceConfigForm";

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
    } finally {
      setLoading(false);
    }
  };

  const s = d.status || {};
  return (
    <div className="card" style={{ display: "grid", gap: "var(--s-3)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "var(--s-3)" }}>
        <span className={`dot ${online ? "dot--ok" : "dot--danger"}`} />
        <strong style={{ fontSize: "var(--t-lg)" }}>{d.name || d.id}</strong>
        <span className="badge" style={{ marginLeft: "auto" }}>
          {online ? "Terhubung" : "Terputus"}
        </span>
      </div>

      {s.data_collection_mode && (
        <div className="notice" style={{ background: "var(--accent)", color: "#fff" }}>
          📷 Mode Ambil Data
          {s.capturing ? " — sedang merekam" : " — siaga"}
          {typeof s.capture_count === "number" && ` · ${s.capture_count} foto`}
        </div>
      )}

      <div style={{ color: "var(--ink-2)", display: "flex", gap: "var(--s-5)", flexWrap: "wrap" }}>
        {s.mode && <span>Mode: <strong>{s.mode}</strong></span>}
        {typeof s.battery === "number" && <span>Baterai: <strong>{s.battery}%</strong></span>}
        {s.wifi && <span>WiFi: <strong>{s.wifi}</strong></span>}
        {d.fw_version && <span style={{ color: "var(--ink-3)" }}>v{d.fw_version}</span>}
      </div>

      {!editing ? (
        <button className="btn" onClick={openEdit} style={{ justifySelf: "start" }}>
          Atur perangkat
        </button>
      ) : loading ? (
        <p style={{ margin: 0, color: "var(--ink-3)" }}>Memuat…</p>
      ) : full ? (
        <div style={{ borderTop: "1px solid var(--border)", paddingTop: "var(--s-4)" }}>
          <DeviceConfigForm device={full} submitLabel="Kirim pengaturan ke perangkat" />
        </div>
      ) : (
        <p className="notice notice--err" style={{ margin: 0 }}>Gagal memuat detail perangkat.</p>
      )}
    </div>
  );
}

export default function DashboardClient() {
  const [authChecked, setAuthChecked] = useState(false);
  const [signedIn, setSignedIn] = useState(false);
  const [devices, setDevices] = useState<DeviceRow[] | null>(null);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    const res = await fetch("/api/devices");
    if (res.status === 401) {
      setSignedIn(false);
      setAuthChecked(true);
      return;
    }
    const data = await res.json();
    if (!res.ok) {
      setErr(data.error || "Gagal memuat perangkat.");
    } else {
      setDevices(data.devices);
    }
    setSignedIn(true);
    setAuthChecked(true);
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 30_000); // refresh status periodically
    return () => clearInterval(t);
  }, [load]);

  if (!authChecked) return <div className="container section">Memuat…</div>;

  if (!signedIn) {
    return (
      <div className="container section" style={{ maxWidth: 460 }}>
        <h1 style={{ fontSize: "var(--t-2xl)", letterSpacing: "-.02em" }}>Perangkat saya</h1>
        <p className="sub">Masuk untuk melihat perangkatmu.</p>
        <Link href="/login?next=/dashboard" className="btn btn--primary btn--lg">Masuk</Link>
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

      {err && <div className="notice notice--err" style={{ marginTop: "var(--s-4)" }}>{err}</div>}

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

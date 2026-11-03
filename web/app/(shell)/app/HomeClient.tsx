"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import AppBar from "@/components/app/AppBar";
import InstallCard from "@/components/InstallCard";
import Notice from "@/components/Notice";
import { SettingsGroup, SettingsItem, SettingsLink } from "@/components/app/Settings";
import { ensureSession, type Session } from "@/lib/supabase/session";
import { deviceLabel, deviceSummary, isOnline, needsSetup, type DeviceRow } from "@/lib/devices";
import { RELAY_PAUSED } from "@/lib/relay";
import { RelayPausedLinks, RelayPausedNotice } from "@/components/app/RelayPaused";

export default function HomeClient() {
  return RELAY_PAUSED ? <PausedHome /> : <LiveHome />;
}

/** The relay is off (lib/relay.ts): no session, no device list, only what works. */
function PausedHome() {
  return (
    <>
      <AppBar title="I-Sora" />
      <div className="app-body">
        <InstallCard />
        <RelayPausedNotice />
        <RelayPausedLinks />
        <p className="sgroup__note" style={{ textAlign: "center" }}>
          Perangkat tetap berfungsi penuh secara offline.{" "}
          <Link href="/docs/masalah-umum">Ada masalah?</Link>
        </p>
      </div>
    </>
  );
}

function LiveHome() {
  const [session, setSession] = useState<Session | null>(null);
  const [devices, setDevices] = useState<DeviceRow[] | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    let alive = true;
    ensureSession().then((s) => alive && setSession(s));
    return () => {
      alive = false;
    };
  }, []);

  // A 401 here means the cookie went stale, not that the user must "log in" —
  // there is no log-in to send them to. Re-mint silently, once, then carry on.
  const recovering = useRef(false);
  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/devices");
      if (res.status === 401) {
        if (recovering.current) return;
        recovering.current = true;
        const s = await ensureSession();
        setSession(s);
        recovering.current = false;
        return;
      }
      const data = await res.json();
      if (!res.ok) {
        setErr(data.error || "Gagal memuat perangkat.");
        return;
      }
      setDevices(data.devices);
      setErr("");
    } catch {
      setErr("Tidak ada koneksi — daftar perangkat mungkin tidak terbaru.");
    }
  }, []);

  useEffect(() => {
    if (session?.kind !== "ok") return;
    load();
    const timer = setInterval(load, 30_000);
    return () => clearInterval(timer);
  }, [session, load]);

  const ready = session?.kind === "ok";

  return (
    <>
      <AppBar title="I-Sora" />
      <div className="app-body">
        <InstallCard />

        {err && <Notice kind="err">{err}</Notice>}

        <SettingsGroup
          title="Perangkat"
          note={
            devices && devices.length > 0
              ? "Ketuk perangkat untuk melihat status dan mengubah pengaturannya."
              : undefined
          }
        >
          {!ready ? (
            <SettingsItem
              label={session ? "Belum bisa terhubung ke relay" : "Menyiapkan…"}
              sub={session?.kind === "none" ? session.reason : undefined}
            />
          ) : devices === null ? (
            <SettingsItem label="Memuat…" />
          ) : devices.length === 0 ? (
            <SettingsItem label="Belum ada perangkat" sub="Tambahkan I-Sora pertamamu di bawah." />
          ) : (
            devices.map((d) => (
              <SettingsLink
                key={d.id}
                href={`/app/${d.id}`}
                lead={
                  <span
                    className={`dot ${
                      // Amber, not red: a device waiting for its setup is not
                      // broken — it is the one row here that wants a tap.
                      needsSetup(d) ? "dot--warn" : isOnline(d) ? "dot--ok" : "dot--danger"
                    }`}
                    aria-hidden="true"
                  />
                }
                label={deviceLabel(d)}
                sub={deviceSummary(d)}
              />
            ))
          )}
          <SettingsLink
            href="/app/tambah"
            label="Tambah perangkat"
            sub="Tekan tombol pada perangkat — tanpa kode, tanpa mengetik"
          />
        </SettingsGroup>

        <SettingsGroup
          title="Coba & pelajari"
          note="Simulasi berjalan sepenuhnya di ponsel — tidak butuh perangkat dan tidak butuh internet setelah terbuka sekali."
        >
          <SettingsLink
            href="/simulasi"
            label="Simulasi kamera"
            sub="Pakai kamera HP seolah-olah kamu memakai I-Sora"
          />
          <SettingsLink href="/preview" label="Coba suara" sub="Dengarkan chime dan sapaan" />
          <SettingsLink href="/docs" label="Panduan" sub="Cara pakai, pemasangan, masalah umum" />
        </SettingsGroup>

        {/*
          There is no account to create — the device list belongs to this browser.
          An email is offered only as a way to carry that list to another phone,
          and as insurance against clearing site data.
        */}
        <SettingsGroup
          title="Cadangan"
          note={
            ready && session.anonymous
              ? "Perangkatmu tersimpan di ponsel ini. Tambahkan email kalau ingin membukanya dari ponsel lain — atau supaya tidak hilang kalau data peramban dihapus."
              : undefined
          }
        >
          {ready && !session.anonymous ? (
            <>
              <SettingsItem label="Tercadangkan ke" value={session.email} />
              <form action="/auth/signout" method="post">
                <button type="submit" className="srow srow--danger">
                  <span className="srow__main">
                    <span className="srow__label">Keluar dari ponsel ini</span>
                  </span>
                </button>
              </form>
            </>
          ) : (
            <SettingsLink
              href="/login?next=/app"
              label="Tambahkan email"
              sub="Opsional · tautan ajaib, tanpa password"
            />
          )}
          <SettingsLink href="/" label="Tentang I-Sora" />
        </SettingsGroup>

        <p className="sgroup__note" style={{ textAlign: "center" }}>
          Perangkat tetap berfungsi penuh secara offline.{" "}
          <Link href="/docs/masalah-umum">Ada masalah?</Link>
        </p>
      </div>
    </>
  );
}

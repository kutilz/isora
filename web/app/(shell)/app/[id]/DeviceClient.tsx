"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import AppBar from "@/components/app/AppBar";
import Notice from "@/components/Notice";
import DeviceSettingsForm from "@/components/app/DeviceSettingsForm";
import WelcomeOverlay from "@/components/app/WelcomeOverlay";
import {
  SettingsButton,
  SettingsGroup,
  SettingsItem,
  SettingsLink,
  StatusPill,
} from "@/components/app/Settings";
import {
  deviceLabel,
  isOnline,
  lastSeenText,
  localUrl,
  mdnsUrl,
  needsSetup,
  type DeviceRow,
} from "@/lib/devices";
import { ensureSession } from "@/lib/supabase/session";
import { useCommandAck } from "@/lib/useCommandAck";

export default function DeviceClient({ id }: { id: string }) {
  const router = useRouter();
  const params = useSearchParams();
  const justPaired = params.get("baru") === "1";

  const [device, setDevice] = useState<DeviceRow | null>(null);
  const [err, setErr] = useState("");
  const [state, setState] = useState<"loading" | "ready" | "nosession" | "missing">("loading");
  const [unlinking, setUnlinking] = useState(false);
  // The first-setup hand-off: which queued command we are watching, and where
  // the hand-off has got to. Watching continues after the welcome closes, so
  // tapping "Lanjut" early never turns into a wrong verdict on this screen.
  const [cmd, setCmd] = useState<string | null>(null);
  const [phase, setPhase] = useState<"idle" | "welcome" | "done">("idle");
  const ack = useCommandAck(id, cmd);

  // When the device took the settings, so a later heartbeat can be told apart
  // from the one already in flight. Needed because an ACK only proves the
  // command was consumed — a secret inside it can still have failed to open
  // (that is exactly how a dead API key went unnoticed once), and the first
  // heartbeat after saving may predate the apply.
  const appliedAt = useRef<number | null>(null);
  useEffect(() => {
    if (ack === "applied" && appliedAt.current === null) appliedAt.current = Date.now();
  }, [ack]);

  // A 401 means the cookie went stale, not that an account is needed — there is
  // no account. Re-mint the anonymous session once and let the poll retry.
  const recovering = useRef(false);
  const load = useCallback(async () => {
    try {
      const res = await fetch(`/api/devices/${id}`);
      if (res.status === 401) {
        if (recovering.current) return;
        recovering.current = true;
        const s = await ensureSession();
        recovering.current = false;
        if (s.kind === "none") {
          setErr(s.reason);
          return setState("nosession");
        }
        return;
      }
      if (res.status === 404) return setState("missing");
      const data = await res.json();
      if (!res.ok) {
        setErr(data.error || "Gagal memuat perangkat.");
        return;
      }
      setDevice(data.device);
      setErr("");
      setState("ready");
    } catch {
      setErr("Tidak ada koneksi — status mungkin tidak terbaru.");
    }
  }, [id]);

  useEffect(() => {
    load();
    const timer = setInterval(load, 20_000);
    return () => clearInterval(timer);
  }, [load]);

  const onSetupSaved = useCallback((commandId: string | null) => {
    setCmd(commandId);
    setPhase("welcome");
  }, []);

  // Leaving the welcome drops `?baru=1`, so a reload does not replay the
  // first-setup screen for a device that is already configured.
  const closeWelcome = useCallback(() => {
    setPhase("done");
    router.replace(`/app/${id}`);
    load();
  }, [router, id, load]);

  const unlink = async () => {
    if (!confirm("Lepaskan perangkat ini dari aplikasi? Perangkat tetap berfungsi, tapi harus dihubungkan ulang untuk diatur dari sini.")) {
      return;
    }
    setUnlinking(true);
    try {
      const res = await fetch(`/api/devices/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error();
      router.push("/app");
    } catch {
      setErr("Gagal melepaskan perangkat.");
      setUnlinking(false);
    }
  };

  if (state === "nosession") {
    return (
      <>
        <AppBar title="Perangkat" back="/app" />
        <div className="app-body">
          <SettingsGroup
            title="Belum bisa menghubungi relay"
            note="Perangkat tetap berfungsi penuh — ini hanya memengaruhi pengaturan dari jauh."
          >
            <SettingsItem label="Sesi tidak bisa dibuat" sub={err || undefined} />
            <SettingsLink href="/docs/masalah-umum" label="Masalah umum" />
          </SettingsGroup>
        </div>
      </>
    );
  }

  if (state === "missing") {
    return (
      <>
        <AppBar title="Perangkat" back="/app" />
        <div className="app-body">
          <SettingsGroup>
            <SettingsItem
              label="Perangkat tidak ditemukan"
              sub="Mungkin sudah dilepaskan dari aplikasi ini."
            />
            <SettingsLink href="/app/tambah" label="Hubungkan perangkat" />
          </SettingsGroup>
        </div>
      </>
    );
  }

  if (!device) {
    return (
      <>
        <AppBar title="Perangkat" back="/app" />
        <div className="app-body" role="status">
          <SettingsGroup>
            <SettingsItem label="Memuat…" />
          </SettingsGroup>
        </div>
      </>
    );
  }

  // Not read from the URL alone: pairing finishes on the DEVICE, so a person
  // who reloads, taps back, or opens this screen tomorrow must still be walked
  // through the setup they never finished. The device says so in its heartbeat.
  const firstSetup = (justPaired || needsSetup(device)) && ack !== "applied";
  // Only trust a heartbeat that is NEWER than the apply; the one before it
  // still describes the device as it was a moment ago.
  const keyRejected =
    appliedAt.current !== null &&
    device.status?.ai_ready === false &&
    !!device.last_seen &&
    new Date(device.last_seen).getTime() > appliedAt.current;
  const online = isOnline(device);
  const s = device.status || {};
  const lan = localUrl(device);
  const mdns = mdnsUrl(device);
  const sameNet = !!device.same_network;

  return (
    <>
      <AppBar
        title={deviceLabel(device)}
        back="/app"
        trailing={<StatusPill online={online} />}
      />
      <div className="app-body">
        {phase === "done" && ack === "applied" && !keyRejected && (
          <Notice kind="ok">
            I-Sora siap dipakai. Semua pengaturan sudah masuk ke perangkat.
          </Notice>
        )}

        {phase === "done" && keyRejected && (
          <Notice kind="warn">
            Pengaturan masuk, tapi <strong>API key belum aktif</strong> di perangkat. Kirim ulang
            API key-nya di bawah — kalau tetap begitu, perangkat mungkin perlu dinyalakan ulang.
          </Notice>
        )}

        {phase === "done" && ack === "waiting" && (
          <Notice kind="info">Pengaturan sedang dikirim ke perangkat…</Notice>
        )}

        {phase === "done" && ack === "slow" && (
          <Notice kind="warn">
            Pengaturan tersimpan, tapi perangkat belum mengambilnya. Nyalakan perangkat dan
            sambungkan ke WiFi — pengaturan masuk sendiri.
          </Notice>
        )}

        {phase === "idle" && firstSetup && (
          <Notice kind="info">
            <strong>Tinggal satu langkah.</strong> Isi pengaturan di bawah, lalu tekan{" "}
            <strong>Simpan &amp; selesai</strong>.
            {justPaired && " Perangkat sudah mengucapkan “Perangkat sudah terhubung.”"}{" "}
            Halaman ini boleh ditutup dulu — perangkat tetap tertaut, dan setelannya bisa
            dilanjutkan kapan saja dari daftar perangkat.
          </Notice>
        )}

        {err && <Notice kind="err">{err}</Notice>}

        {s.data_collection_mode && (
          <Notice kind="warn" alert>
            <strong>Mode Ambil Data aktif</strong>
            {s.capturing ? " — sedang merekam" : " — siaga"}
            {typeof s.capture_count === "number" && ` · ${s.capture_count} foto`}. Fitur asistif
            perangkat nonaktif selama mode ini.
          </Notice>
        )}

        <SettingsGroup title="Status">
          <SettingsItem label="Koneksi" value={online ? "Terhubung" : "Terputus"} />
          {!online && device.last_seen && (
            <SettingsItem label="Terakhir terlihat" value={lastSeenText(device.last_seen)} />
          )}
          {s.mode && <SettingsItem label="Mode" value={s.mode} />}
          {s.mode === "explorer" && typeof s.scan_active === "boolean" && (
            <SettingsItem label="Navigasi daring" value={s.scan_active ? "Menyala" : "Mati"} />
          )}
          {typeof s.battery === "number" && <SettingsItem label="Baterai" value={`${s.battery}%`} />}
          {s.wifi && <SettingsItem label="WiFi" value={s.wifi} />}
          {s.ai_ready === false && (
            <SettingsItem
              label="Deskripsi suasana"
              sub="Belum ada API key — isi di bagian Pengaturan di bawah"
              value="Nonaktif"
            />
          )}
          {device.fw_version && <SettingsItem label="Versi perangkat lunak" value={device.fw_version} />}
          <SettingsItem label="ID perangkat" value={<code>{device.id}</code>} />
        </SettingsGroup>

        <SettingsGroup
          title="Kendali lokal"
          note={
            sameNet ? (
              <>
                Halaman ini dilayani langsung oleh perangkat lewat WiFi — tidak lewat internet.
                {mdns && (
                  <>
                    {" "}
                    Alamat tetapnya: <code>{mdns.replace(/^https?:\/\//, "")}</code> (belum tentu
                    bisa dibuka di Android).
                  </>
                )}
              </>
            ) : (
              "Kendali lokal hanya terbuka dari WiFi yang sama dengan perangkat. Sambungkan ponsel ke WiFi itu, lalu buka halaman ini lagi."
            )
          }
        >
          {sameNet && lan ? (
            <>
              <SettingsLink
                href={`${lan}/buttons`}
                external
                label="Kendali tombol"
                sub="Konsol tombol besar untuk pengguna netra"
              />
              <SettingsLink
                href={`${lan}/`}
                external
                label="Panel perangkat"
                sub="Dashboard lengkap di perangkat"
              />
            </>
          ) : (
            <SettingsItem
              label="Tidak tersedia sekarang"
              sub={
                lan
                  ? "Ponsel sedang tidak di WiFi yang sama dengan perangkat."
                  : "Perangkat belum melaporkan alamat lokalnya."
              }
            />
          )}
        </SettingsGroup>

        <DeviceSettingsForm
          device={device}
          firstSetup={firstSetup}
          onDone={load}
          onSetupSaved={onSetupSaved}
        />

        <SettingsGroup
          title="Lanjutan"
          note="Melepaskan tidak menghapus apa pun di perangkat — hanya memutus tautannya dari aplikasi ini."
        >
          <SettingsButton
            label={unlinking ? "Melepaskan…" : "Lepaskan perangkat"}
            danger
            disabled={unlinking}
            onClick={unlink}
          />
        </SettingsGroup>
      </div>

      {phase === "welcome" && (
        <WelcomeOverlay name={deviceLabel(device)} ack={ack} onContinue={closeWelcome} />
      )}
    </>
  );
}

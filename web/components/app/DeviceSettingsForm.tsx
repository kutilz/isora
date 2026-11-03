"use client";

import { useState } from "react";
import { sealToDevice } from "@/lib/e2e";
import { useCommandAck } from "@/lib/useCommandAck";
import Notice from "@/components/Notice";
import { SettingsField, SettingsGroup } from "@/components/app/Settings";
import type { DeviceRow } from "@/lib/devices";

type Provider = "openai" | "gemini" | "claude";

/** Choices for the online-navigation interval. The device accepts any 3-60 s
 * (the /buttons slider can set e.g. 12), so the reported value is added to the
 * list when it is not one of these. */
const SCAN_INTERVALS = [5, 8, 10, 15, 20, 30, 45, 60];

const PROVIDERS: { id: Provider; label: string; keyField: string; placeholder: string }[] = [
  { id: "openai", label: "OpenAI", keyField: "openai_api_key", placeholder: "sk-…" },
  { id: "gemini", label: "Google Gemini", keyField: "gemini_api_key", placeholder: "AIza…" },
  { id: "claude", label: "Anthropic Claude", keyField: "claude_api_key", placeholder: "sk-ant-…" },
];

/**
 * Device settings as a grouped form. The API key is sealed to the device's
 * public key in the browser (lib/e2e) — the relay only ever relays ciphertext.
 *
 * `firstSetup` sends every field including untouched defaults, which is what a
 * freshly claimed device needs. Afterwards only touched fields are sent, so
 * renaming a device can never silently reset its provider or audio mode.
 *
 * Saving is never a dead end: the queued command is watched until the device
 * applies it (useCommandAck), and on first setup the screen hands over to the
 * welcome transition instead of leaving a green box on an unchanged page.
 */
export default function DeviceSettingsForm({
  device,
  firstSetup = false,
  onDone,
  onSetupSaved,
}: {
  device: DeviceRow;
  firstSetup?: boolean;
  onDone?: () => void;
  /** First setup only: the parent takes over with the welcome transition. */
  onSetupSaved?: (commandId: string | null) => void;
}) {
  const [provider, setProvider] = useState<Provider>("openai");
  const [apiKey, setApiKey] = useState("");
  const [audioMode, setAudioMode] = useState<"both" | "chime" | "speech">("both");
  const [deviceName, setDeviceName] = useState(device.name || "");
  const reportedInterval =
    typeof device.status?.scan_interval_s === "number"
      ? Math.round(device.status.scan_interval_s)
      : 8;
  const [scanInterval, setScanInterval] = useState(reportedInterval);
  const intervalChoices = SCAN_INTERVALS.includes(reportedInterval)
    ? SCAN_INTERVALS
    : [...SCAN_INTERVALS, reportedInterval].sort((a, b) => a - b);
  const [dirty, setDirty] = useState({ provider: false, audio: false, name: false, scan: false });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [ok, setOk] = useState(false);
  const [commandId, setCommandId] = useState<string | null>(null);
  const ack = useCommandAck(device.id, commandId);

  const prov = PROVIDERS.find((p) => p.id === provider)!;
  const markDirty = (field: keyof typeof dirty) =>
    setDirty((v) => (v[field] ? v : { ...v, [field]: true }));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    setOk(false);

    const config: Record<string, unknown> = {};
    if (firstSetup || dirty.provider) config.ai_provider = provider;
    if (firstSetup || dirty.audio) config.audio_mode = audioMode;
    if ((firstSetup || dirty.name) && deviceName.trim()) config.device_name = deviceName.trim();
    if (firstSetup || dirty.scan) config.scan_interval_s = scanInterval;
    if (firstSetup) config.setup_completed = true;

    const key = apiKey.trim();
    if (!key && Object.keys(config).length === 0) {
      setErr("Belum ada perubahan untuk dikirim.");
      return;
    }

    setBusy(true);
    try {
      const secrets: Record<string, unknown> = {};
      if (key) {
        if (!device.pubkey) {
          throw new Error(
            "Perangkat ini belum mendukung enkripsi key lewat cloud. Atur API key lewat halaman kendali lokal perangkat."
          );
        }
        secrets[prov.keyField] = await sealToDevice(key, device.pubkey);
      }

      const res = await fetch(`/api/devices/${device.id}/config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ config, secrets }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Gagal menyimpan pengaturan.");
      setApiKey("");
      onDone?.();
      if (firstSetup) {
        onSetupSaved?.(data.command_id ?? null);
        return;
      }
      setCommandId(data.command_id ?? null);
      setOk(true);
    } catch (e: any) {
      setErr(e?.message || "Gagal menyimpan pengaturan.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} style={{ display: "grid", gap: "var(--s-6)" }}>
      <SettingsGroup
        title="Pengaturan"
        note={
          firstSetup
            ? "Pengaturan ini dikirim ke perangkat lewat koneksi aman begitu disimpan."
            : "Hanya kolom yang diubah yang akan dikirim ke perangkat."
        }
      >
        <SettingsField>
          <div className="field">
            <label htmlFor="dev-name">Nama perangkat</label>
            <input
              id="dev-name"
              className="input"
              value={deviceName}
              onChange={(e) => {
                setDeviceName(e.target.value);
                markDirty("name");
              }}
              placeholder="isora-rumah"
            />
            <span className="hint">Dipakai juga sebagai alamat lokal perangkat di WiFi.</span>
          </div>
        </SettingsField>

        <SettingsField>
          <div className="field">
            <label htmlFor="dev-prov">Layanan AI</label>
            <select
              id="dev-prov"
              className="select"
              value={provider}
              onChange={(e) => {
                setProvider(e.target.value as Provider);
                markDirty("provider");
              }}
            >
              {PROVIDERS.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </select>
          </div>
        </SettingsField>

        <SettingsField>
          <div className="field">
            <label htmlFor="dev-key">API key {prov.label}</label>
            <input
              id="dev-key"
              className="input"
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={prov.placeholder}
              autoComplete="off"
            />
            <span className="hint">
              Dienkripsi di browser ke perangkat ini — server kami tidak melihat key aslinya.
              Kosongkan bila tak ingin mengubahnya.
            </span>
          </div>
        </SettingsField>

        <SettingsField>
          <div className="field">
            <label htmlFor="dev-audio">Cara mendengar</label>
            <select
              id="dev-audio"
              className="select"
              value={audioMode}
              onChange={(e) => {
                setAudioMode(e.target.value as "both" | "chime" | "speech");
                markDirty("audio");
              }}
            >
              <option value="both">Chime + bicara (default)</option>
              <option value="chime">Hanya chime (mahir)</option>
              <option value="speech">Hanya bicara (pemula)</option>
            </select>
          </div>
        </SettingsField>

        <SettingsField>
          <div className="field">
            <label htmlFor="dev-scan">Jarak kabar navigasi daring</label>
            <select
              id="dev-scan"
              className="select"
              value={scanInterval}
              aria-describedby="dev-scan-hint"
              onChange={(e) => {
                setScanInterval(Number(e.target.value));
                markDirty("scan");
              }}
            >
              {intervalChoices.map((sec) => (
                <option key={sec} value={sec}>
                  {sec} detik{sec === 8 ? " (default)" : ""}
                </option>
              ))}
            </select>
            <span className="hint" id="dev-scan-hint">
              Di mode penjelajah, tombol ACTION menyalakan navigasi daring: perangkat memotret
              berkala dan membacakan jalur, tangga, pintu, dan tulisan papan. Makin sering, makin
              banyak pemakaian API key.
            </span>
          </div>
        </SettingsField>
      </SettingsGroup>

      {err && <Notice kind="err">{err}</Notice>}
      {ok && (
        <Notice kind={ack === "slow" ? "warn" : "ok"}>
          {ack === "applied"
            ? "Perangkat sudah menerapkan pengaturan."
            : ack === "slow"
              ? "Tersimpan. Perangkat belum mengambilnya — akan diterapkan sendiri begitu perangkat online."
              : "Mengirim ke perangkat…"}
        </Notice>
      )}

      <button className="btn btn--primary btn--lg" type="submit" disabled={busy}>
        {busy ? "Mengirim…" : firstSetup ? "Simpan & selesai" : "Kirim ke perangkat"}
      </button>
    </form>
  );
}

"use client";

import { useState } from "react";
import { sealToDevice } from "@/lib/e2e";

export type Device = { id: string; name: string | null; pubkey: string | null };
type Provider = "openai" | "gemini" | "claude";

const PROVIDERS: { id: Provider; label: string; keyField: string; placeholder: string }[] = [
  { id: "openai", label: "OpenAI", keyField: "openai_api_key", placeholder: "sk-…" },
  { id: "gemini", label: "Google Gemini", keyField: "gemini_api_key", placeholder: "AIza…" },
  { id: "claude", label: "Anthropic Claude", keyField: "claude_api_key", placeholder: "sk-ant-…" },
];

/**
 * Reusable config wizard. Encrypts the API key client-side to the device pubkey
 * (E2E) and pushes a config command via /api/devices/:id/config.
 * Used by /pair (first setup) and /dashboard (re-configure).
 */
export default function DeviceConfigForm({
  device,
  onDone,
  submitLabel = "Simpan & kirim ke perangkat",
}: {
  device: Device;
  onDone?: () => void;
  submitLabel?: string;
}) {
  const [provider, setProvider] = useState<Provider>("openai");
  const [apiKey, setApiKey] = useState("");
  const [audioMode, setAudioMode] = useState<"both" | "chime" | "speech">("both");
  const [deviceName, setDeviceName] = useState(device.name || "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [ok, setOk] = useState(false);

  const prov = PROVIDERS.find((p) => p.id === provider)!;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    setOk(false);
    setBusy(true);
    try {
      const config: Record<string, unknown> = {
        ai_provider: provider,
        audio_mode: audioMode,
        setup_completed: true,
      };
      if (deviceName.trim()) config.device_name = deviceName.trim();

      const secrets: Record<string, unknown> = {};
      const key = apiKey.trim();
      if (key) {
        if (!device.pubkey) {
          throw new Error(
            "Perangkat ini belum mendukung enkripsi key lewat cloud. Atur API key lewat setup lokal perangkat."
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
      setOk(true);
      onDone?.();
    } catch (e: any) {
      setErr(e?.message || "Gagal menyimpan pengaturan.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} style={{ display: "grid", gap: "var(--s-4)" }}>
      <div className="field">
        <label htmlFor={`name-${device.id}`}>Nama perangkat</label>
        <input id={`name-${device.id}`} className="input" value={deviceName}
          onChange={(e) => setDeviceName(e.target.value)} placeholder="isora-rumah" />
      </div>

      <div className="field">
        <label htmlFor={`prov-${device.id}`}>Layanan AI</label>
        <select id={`prov-${device.id}`} className="select" value={provider}
          onChange={(e) => setProvider(e.target.value as Provider)}>
          {PROVIDERS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
        </select>
      </div>

      <div className="field">
        <label htmlFor={`key-${device.id}`}>API key {prov.label}</label>
        <input id={`key-${device.id}`} className="input" type="password" value={apiKey}
          onChange={(e) => setApiKey(e.target.value)} placeholder={prov.placeholder} autoComplete="off" />
        <span className="hint">
          Dienkripsi di browser ke perangkatmu — server kami tidak melihat key aslinya.
          Kosongkan bila tak ingin mengubahnya.
        </span>
      </div>

      <div className="field">
        <label htmlFor={`audio-${device.id}`}>Cara mendengar</label>
        <select id={`audio-${device.id}`} className="select" value={audioMode}
          onChange={(e) => setAudioMode(e.target.value as any)}>
          <option value="both">Chime + bicara (default)</option>
          <option value="chime">Hanya chime (mahir)</option>
          <option value="speech">Hanya bicara (pemula)</option>
        </select>
      </div>

      {err && <div className="notice notice--err">{err}</div>}
      {ok && <div className="notice notice--ok">Pengaturan terkirim ke perangkat.</div>}
      <button className="btn btn--primary btn--lg" type="submit" disabled={busy}>
        {busy ? "Mengirim…" : submitLabel}
      </button>
    </form>
  );
}

import { useEffect, useRef, useState } from "preact/hooks";
import { Icon } from "../atoms/Icon";
import { apiPost } from "../../lib/api";
import { t } from "../../lib/i18n";

type AudioMode = "chime" | "speech" | "both";

/**
 * Volume slider + audio_mode preference dropdown.
 *
 * Volume writes are debounced 200 ms so dragging the slider doesn't spam
 * the device with /config POSTs. audio_mode writes immediately on change
 * since it's a discrete choice.
 */
export function VolumeControl({
  initialVolume,
  initialMode,
}: {
  initialVolume: number;
  initialMode: AudioMode;
}) {
  const [value, setValue] = useState(initialVolume);
  const [mode, setMode] = useState<AudioMode>(initialMode);

  // sync if parent's status snapshot changes (e.g. operator updated elsewhere)
  useEffect(() => setValue(initialVolume), [initialVolume]);
  useEffect(() => setMode(initialMode), [initialMode]);

  const debounceTimer = useRef<number | undefined>(undefined);
  const writeVolume = (v: number) => {
    if (debounceTimer.current) window.clearTimeout(debounceTimer.current);
    debounceTimer.current = window.setTimeout(() => {
      apiPost("/config", { audio_volume: v }).catch(() => {});
    }, 200);
  };
  const changeVolume = (v: number) => {
    const clamped = Math.max(0, Math.min(100, v));
    setValue(clamped);
    writeVolume(clamped);
  };
  const changeMode = (m: AudioMode) => {
    setMode(m);
    apiPost("/config", { audio_mode: m }).catch(() => {});
  };
  const playSample = () =>
    apiPost("/command", { cmd: "describe" }).catch(() => {});

  return (
    <section
      class="card"
      aria-labelledby="vol-title"
      style={{ padding: "var(--s-5)" }}
    >
      <h2
        id="vol-title"
        style={{
          margin: 0,
          fontSize: "var(--t-lg)",
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}
      >
        <Icon name="speaker" size={22} /> {t("volume.title")}
        <span class="badge" style={{ marginLeft: "auto" }}>{value}%</span>
      </h2>
      <p
        style={{
          margin: "var(--s-2) 0 var(--s-4)",
          color: "var(--ink-3)",
          fontSize: "var(--t-sm)",
        }}
      >
        Pastikan pengguna mendengar dengan jelas di lingkungannya. Pintasan:{" "}
        <kbd class="kbd">+</kbd> / <kbd class="kbd">−</kbd>.
      </p>
      <div style={{ display: "flex", alignItems: "center", gap: "var(--s-3)" }}>
        <button
          type="button"
          class="btn btn--icon"
          aria-label={t("volume.softer")}
          onClick={() => changeVolume(value - 10)}
        >
          <Icon name="minus" size={20} />
        </button>
        <div style={{ flex: 1 }}>
          <input
            type="range"
            min={0}
            max={100}
            step={5}
            value={value}
            aria-label="Volume speaker"
            onInput={(e) =>
              changeVolume(parseInt((e.currentTarget as HTMLInputElement).value))
            }
            style={{ width: "100%", accentColor: "var(--accent)", height: 32 }}
          />
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              fontSize: "var(--t-xs)",
              color: "var(--ink-3)",
              marginTop: -4,
            }}
          >
            <span>Pelan</span>
            <span>Sedang</span>
            <span>Keras</span>
          </div>
        </div>
        <button
          type="button"
          class="btn btn--icon"
          aria-label={t("volume.louder")}
          onClick={() => changeVolume(value + 10)}
        >
          <Icon name="plus" size={20} />
        </button>
      </div>
      <button
        type="button"
        class="btn"
        onClick={playSample}
        style={{ marginTop: "var(--s-4)", width: "100%" }}
      >
        <Icon name="play" size={18} /> {t("volume.play_sample")}
      </button>

      <hr
        style={{
          border: "none",
          borderTop: "1px solid var(--border)",
          margin: "var(--s-5) 0 var(--s-4)",
        }}
      />
      <div>
        <label htmlFor="audio-mode" style={{ fontWeight: 600, fontSize: "var(--t-sm)" }}>
          {t("volume.audio_mode")}
        </label>
        <select
          id="audio-mode"
          value={mode}
          onChange={(e) =>
            changeMode((e.currentTarget as HTMLSelectElement).value as AudioMode)
          }
          style={{
            width: "100%",
            marginTop: 6,
            font: "inherit",
            padding: "12px 14px",
            borderRadius: "var(--r-md)",
            border: "2px solid var(--border-strong)",
            background: "var(--surface)",
            color: "var(--ink)",
            minHeight: 48,
          }}
        >
          <option value="both">{t("volume.audio_mode_both")}</option>
          <option value="chime">{t("volume.audio_mode_chime")}</option>
          <option value="speech">{t("volume.audio_mode_speech")}</option>
        </select>
      </div>
    </section>
  );
}

export type { AudioMode };

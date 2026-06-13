import { Icon, type IconName } from "../atoms/Icon";
import { apiPost } from "../../lib/api";
import { t } from "../../lib/i18n";

type Mode = "explorer" | "context" | "qris";

const MODES: { id: Mode; icon: IconName; nameKey: string; subKey: string }[] = [
  { id: "explorer", icon: "explore", nameKey: "modes.explorer", subKey: "modes.explorer_sub" },
  { id: "context",  icon: "scene",   nameKey: "modes.context",  subKey: "modes.context_sub" },
  { id: "qris",     icon: "qris",    nameKey: "modes.qris",     subKey: "modes.qris_sub" },
];

export function ModeSwitcher({
  active,
  onOptimistic,
}: {
  active: Mode;
  onOptimistic: (m: Mode) => void;
}) {
  const change = async (m: Mode) => {
    if (m === active) return;
    onOptimistic(m); // optimistic — server will confirm via next /status poll
    try {
      await apiPost("/command", { cmd: "set_mode", mode: m });
    } catch {
      /* swallow; next status tick will correct UI */
    }
  };
  return (
    <section
      class="card"
      aria-labelledby="mode-title"
      style={{ padding: "var(--s-5)" }}
    >
      <h2
        id="mode-title"
        style={{
          margin: "0 0 var(--s-2)",
          fontSize: "var(--t-lg)",
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}
      >
        <Icon name="settings" size={22} /> Mode aktif
      </h2>
      <p
        style={{
          margin: "0 0 var(--s-4)",
          color: "var(--ink-3)",
          fontSize: "var(--t-sm)",
        }}
      >
        Ganti mode dari jarak jauh. Perubahan langsung diumumkan ke pengguna.
        Pintasan keyboard: <kbd class="kbd">1</kbd> <kbd class="kbd">2</kbd>{" "}
        <kbd class="kbd">3</kbd>.
      </p>
      <div
        role="radiogroup"
        aria-labelledby="mode-title"
        style={{ display: "grid", gap: "var(--s-3)" }}
      >
        {MODES.map((m) => {
          const on = m.id === active;
          return (
            <button
              key={m.id}
              type="button"
              role="radio"
              aria-checked={on}
              onClick={() => change(m.id)}
              style={{
                font: "inherit",
                textAlign: "left",
                display: "grid",
                gridTemplateColumns: "auto 1fr auto",
                alignItems: "center",
                gap: "var(--s-4)",
                padding: "var(--s-4) var(--s-5)",
                minHeight: 72,
                background: on ? "var(--accent-soft)" : "var(--surface)",
                border: on ? "3px solid var(--accent)" : "2px solid var(--border)",
                color: "var(--ink)",
                borderRadius: "var(--r-md)",
                cursor: "pointer",
              }}
            >
              <span
                style={{
                  width: 48,
                  height: 48,
                  borderRadius: "50%",
                  background: on ? "var(--accent)" : "var(--surface-2)",
                  color: on ? "var(--ink-inverse)" : "var(--ink-2)",
                  display: "grid",
                  placeItems: "center",
                }}
              >
                <Icon name={m.icon} size={26} />
              </span>
              <span>
                <div style={{ fontSize: "var(--t-md)", fontWeight: 700 }}>
                  {t(m.nameKey)}
                </div>
                <div
                  style={{ fontSize: "var(--t-sm)", color: "var(--ink-3)" }}
                >
                  {t(m.subKey)}
                </div>
              </span>
              <span aria-hidden="true">
                {on ? (
                  <span class="badge badge--accent">AKTIF</span>
                ) : (
                  <Icon name="arrowRight" size={20} />
                )}
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

export type { Mode };

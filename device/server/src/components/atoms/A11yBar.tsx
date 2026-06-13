import { useEffect, useState } from "preact/hooks";
import { bootstrapA11y, saveA11y, type A11yState } from "../../lib/a11y";
import { t, getLang, setLang } from "../../lib/i18n";
import { Icon } from "./Icon";

/**
 * Top accessibility strip — handoff §6.1, §10.
 * Three live toggles (kontras tinggi, teks besar, kurangi animasi). State
 * persists to localStorage and applies instantly via data-* attrs on
 * <html>.
 *
 * Designed to be the FIRST visual element on every page (above the app
 * header) so it's never hidden by content overlap and screen readers
 * land on it early.
 */
export function A11yBar() {
  const [state, setState] = useState<A11yState>(() => bootstrapA11y());

  useEffect(() => {
    saveA11y(state);
  }, [state]);

  const set = <K extends keyof A11yState>(key: K, value: A11yState[K]) =>
    setState((s) => ({ ...s, [key]: value }));

  return (
    <div
      class="a11y-bar"
      role="region"
      aria-label={t("a11y.title")}
      style={{
        background: "var(--surface-2)",
        borderBottom: "1px solid var(--border)",
        padding: "6px var(--s-5)",
        display: "flex",
        alignItems: "center",
        gap: "var(--s-4)",
        flexWrap: "wrap",
        fontSize: "var(--t-sm)",
      }}
    >
      <span style={{ color: "var(--ink-2)", fontWeight: 600 }}>
        <Icon name="contrast" size={16} /> {t("a11y.title")}
      </span>
      <A11yToggle
        icon="contrast"
        label={t("a11y.high_contrast")}
        checked={state.highContrast}
        onChange={(v) => set("highContrast", v)}
      />
      <A11yToggle
        icon="text"
        label={t("a11y.large_type")}
        checked={state.largeType}
        onChange={(v) => set("largeType", v)}
      />
      <A11yToggle
        icon="bellOff"
        label={t("a11y.reduce_motion")}
        checked={state.reduceMotion}
        onChange={(v) => set("reduceMotion", v)}
      />
      <label style={{ marginLeft: "auto" }}>
        <span class="sr-only">{t("a11y.title")} — Language</span>
        <select onChange={(e) => setLang((e.target as HTMLSelectElement).value as "id" | "en")} value={getLang()}>
          <option value="id">Indonesia</option>
          <option value="en">English</option>
        </select>
      </label>
    </div>
  );
}

function A11yToggle({
  icon,
  label,
  checked,
  onChange,
}: {
  icon: string;
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 8,
        cursor: "pointer",
        padding: "4px 8px",
        borderRadius: "var(--r-sm)",
        background: checked ? "var(--accent-soft)" : "transparent",
        color: checked ? "var(--accent-ink)" : "var(--ink-2)",
        fontWeight: checked ? 600 : 500,
      }}
    >
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange((e.target as HTMLInputElement).checked)}
        style={{ width: 16, height: 16, accentColor: "var(--accent)" }}
        aria-label={label}
      />
      <Icon name={icon} size={16} />
      <span>{label}</span>
    </label>
  );
}

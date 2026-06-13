import { useState } from "preact/hooks";
import { apiPost, getToken } from "../../lib/api";
import { t } from "../../lib/i18n";

type AudioMode = "chime" | "speech" | "both";

const OPTIONS: { value: AudioMode; label: string; hint: string }[] = [
  { value: "both",   label: "Chime + bicara",   hint: "Default — chime singkat dulu, lalu suara bicara kalau ada info penting." },
  { value: "chime",  label: "Hanya chime",      hint: "Cocok untuk pengguna mahir yang sudah hapal arti tiap chime." },
  { value: "speech", label: "Hanya bicara",     hint: "Cocok untuk minggu pertama — semuanya diumumkan dengan kalimat." },
];

/**
 * Preference picker — handoff §2.5. Saves audio_mode preference.
 * If logged-out (no device token), generates a shareable URL the
 * pendamping can apply later from the setup wizard.
 */
export function PreferencePicker() {
  const [choice, setChoice] = useState<AudioMode>("both");
  const [state, setState] = useState<"idle" | "saving" | "saved" | "error" | "linked">(
    "idle",
  );
  const [shareUrl, setShareUrl] = useState<string>("");

  const handleSave = async () => {
    if (!getToken()) {
      // Logged-out → emit shareable link instead of saving directly.
      const url = `${window.location.origin}/setup?audio_mode=${choice}`;
      try {
        await navigator.clipboard.writeText(url);
        setShareUrl(url);
        setState("linked");
      } catch {
        setShareUrl(url);
        setState("linked");
      }
      return;
    }
    setState("saving");
    try {
      await apiPost("/config", { audio_mode: choice });
      setState("saved");
    } catch {
      setState("error");
    }
  };

  return (
    <section
      id="preference"
      style={{ padding: "var(--s-12) var(--s-5)", background: "var(--accent-soft)" }}
    >
      <div style={{ maxWidth: 720, margin: "0 auto" }}>
        <h2 class="section-title" style={{ marginTop: 0 }}>
          {t("guide.pref_title")}
        </h2>
        <p class="section-sub">
          Mau dengar chime saja, suara bicara saja, atau keduanya? Kamu bisa
          ubah ini kapan saja dari Beranda pendamping.
        </p>

        <fieldset
          role="radiogroup"
          aria-labelledby="preference-title"
          style={{ border: 0, padding: 0, margin: 0 }}
        >
          <legend id="preference-title" class="sr-only">
            {t("guide.pref_title")}
          </legend>
          <div class="stack">
            {OPTIONS.map((opt) => {
              const selected = choice === opt.value;
              return (
                <label
                  key={opt.value}
                  style={{
                    display: "flex",
                    gap: "var(--s-3)",
                    alignItems: "flex-start",
                    background: selected ? "var(--surface)" : "var(--bg)",
                    border: selected
                      ? "2px solid var(--accent)"
                      : "2px solid var(--border)",
                    borderRadius: "var(--r-md)",
                    padding: "var(--s-4)",
                    cursor: "pointer",
                    minHeight: "var(--hit)",
                  }}
                >
                  <input
                    type="radio"
                    name="audio_mode"
                    value={opt.value}
                    checked={selected}
                    onChange={() => setChoice(opt.value)}
                    style={{ marginTop: 4, accentColor: "var(--accent)" }}
                  />
                  <span>
                    <span style={{ fontWeight: 700, fontSize: "var(--t-md)" }}>
                      {opt.label}
                    </span>
                    <span
                      style={{
                        display: "block",
                        color: "var(--ink-3)",
                        fontSize: "var(--t-sm)",
                        marginTop: 4,
                      }}
                    >
                      {opt.hint}
                    </span>
                  </span>
                </label>
              );
            })}
          </div>
        </fieldset>

        <div
          style={{
            display: "flex",
            gap: "var(--s-3)",
            marginTop: "var(--s-5)",
            flexWrap: "wrap",
            alignItems: "center",
          }}
        >
          <button
            type="button"
            class="btn btn--primary btn--lg"
            onClick={handleSave}
            disabled={state === "saving"}
          >
            {getToken() ? t("guide.pref_save") : t("guide.pref_share")}
          </button>
          <span
            role="status"
            aria-live="polite"
            style={{
              color:
                state === "error"
                  ? "var(--danger)"
                  : state === "saved" || state === "linked"
                    ? "var(--ok)"
                    : "var(--ink-3)",
              fontSize: "var(--t-sm)",
            }}
          >
            {state === "saving" && t("common.loading")}
            {state === "saved" && "Tersimpan."}
            {state === "linked" && "Link disalin ke clipboard."}
            {state === "error" && t("common.error")}
          </span>
        </div>
        {state === "linked" && shareUrl && (
          <p
            style={{
              fontSize: "var(--t-xs)",
              color: "var(--ink-3)",
              marginTop: 8,
              wordBreak: "break-all",
            }}
          >
            {shareUrl}
          </p>
        )}
      </div>
    </section>
  );
}

import { useMemo, useState } from "preact/hooks";
import { Icon, type IconName } from "../atoms/Icon";
import type { HistoryItem } from "./types";
import { t } from "../../lib/i18n";

const FILTERS: { key: string; labelKey: string }[] = [
  { key: "all",      labelKey: "activity.filter_all" },
  { key: "explorer", labelKey: "activity.filter_explorer" },
  { key: "scene",    labelKey: "activity.filter_context" },
  { key: "qris",     labelKey: "activity.filter_qris" },
  { key: "system",   labelKey: "activity.filter_system" },
];

function modeToFilter(mode: string): string {
  if (mode === "scene") return "scene";
  if (mode === "qris")  return "qris";
  if (mode === "explorer") return "explorer";
  return "system";
}

function modeIcon(mode: string): IconName {
  if (mode === "qris")     return "qris";
  if (mode === "scene")    return "scene";
  if (mode === "explorer") return "explore";
  return "info";
}

export function ActivityFeed({ items }: { items: HistoryItem[] }) {
  const [filter, setFilter] = useState("all");
  const filtered = useMemo(
    () =>
      filter === "all"
        ? items
        : items.filter((i) => modeToFilter(i.mode) === filter),
    [items, filter],
  );

  const exportCsv = () => {
    const rows = [
      ["time", "mode", "priority", "module", "text"],
      ...items.map((i) => [i.t_iso, i.mode, i.priority, i.module, i.text]),
    ];
    const csv = rows
      .map((r) =>
        r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(","),
      )
      .join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `auralai-history-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  return (
    <section
      class="card"
      aria-labelledby="act-title"
      style={{ padding: "var(--s-5)" }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "center",
          gap: "var(--s-3)",
          marginBottom: "var(--s-3)",
          flexWrap: "wrap",
        }}
      >
        <h2
          id="act-title"
          style={{
            margin: 0,
            fontSize: "var(--t-lg)",
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          <Icon name="history" size={22} /> {t("activity.title")}
        </h2>
        <span class="badge">{filtered.length}</span>
        <div
          role="group"
          aria-label="Filter riwayat"
          style={{
            marginLeft: "auto",
            display: "flex",
            gap: 4,
            background: "var(--surface-2)",
            padding: 4,
            borderRadius: "var(--r-pill)",
            flexWrap: "wrap",
          }}
        >
          {FILTERS.map(({ key, labelKey }) => (
            <button
              key={key}
              type="button"
              onClick={() => setFilter(key)}
              aria-pressed={filter === key}
              style={{
                font: "inherit",
                padding: "6px 12px",
                border: "none",
                background:
                  filter === key ? "var(--ink)" : "transparent",
                color:
                  filter === key ? "var(--ink-inverse)" : "var(--ink-2)",
                borderRadius: "var(--r-pill)",
                fontSize: "var(--t-xs)",
                fontWeight: 600,
                cursor: "pointer",
                minHeight: 32,
              }}
            >
              {t(labelKey)}
            </button>
          ))}
        </div>
      </header>

      {filtered.length === 0 ? (
        <p style={{ color: "var(--ink-3)", fontSize: "var(--t-sm)" }}>
          {t("activity.empty")}
        </p>
      ) : (
        <ol style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {filtered.map((item, i) => (
            <li
              key={`${item.t_iso}-${i}`}
              style={{
                display: "grid",
                gridTemplateColumns: "auto auto 1fr auto",
                gap: "var(--s-3)",
                alignItems: "center",
                padding: "var(--s-3) 0",
                borderBottom:
                  i < filtered.length - 1 ? "1px solid var(--border)" : "none",
              }}
            >
              <time
                dateTime={item.t_iso}
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: "var(--t-sm)",
                  color: "var(--ink-3)",
                  minWidth: 50,
                }}
              >
                {item.t}
              </time>
              <span
                style={{
                  width: 36,
                  height: 36,
                  borderRadius: "50%",
                  display: "grid",
                  placeItems: "center",
                  background:
                    item.priority === "high"
                      ? "var(--danger-soft)"
                      : item.priority === "normal"
                        ? "var(--accent-soft)"
                        : "var(--surface-2)",
                  color:
                    item.priority === "high"
                      ? "var(--danger)"
                      : item.priority === "normal"
                        ? "var(--accent-ink)"
                        : "var(--ink-3)",
                }}
              >
                <Icon name={modeIcon(item.mode)} size={18} />
              </span>
              <span style={{ fontSize: "var(--t-base)" }}>{item.text}</span>
              <span
                class={`badge badge--${
                  item.priority === "high"
                    ? "danger"
                    : item.priority === "normal"
                      ? "ok"
                      : "info"
                }`}
              >
                {item.priority === "high"
                  ? "Penting"
                  : item.priority === "normal"
                    ? "Info"
                    : "Latar"}
              </span>
            </li>
          ))}
        </ol>
      )}

      <div style={{ marginTop: "var(--s-4)", display: "flex", gap: "var(--s-3)" }}>
        <button type="button" class="btn" onClick={exportCsv} disabled={items.length === 0}>
          <Icon name="download" size={18} /> {t("activity.export")}
        </button>
      </div>
    </section>
  );
}

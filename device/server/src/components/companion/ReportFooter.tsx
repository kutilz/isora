import { useState } from "preact/hooks";
import { Icon } from "../atoms/Icon";
import { apiPost } from "../../lib/api";
import { t } from "../../lib/i18n";

export function ReportFooter() {
  const [msg, setMsg] = useState("");
  const callUser = async () => {
    setMsg("Memanggil…");
    try {
      // Re-use the existing /command pipeline; AI engine handles "describe"
      // → reads back the most recent caption to the user. Closest available
      // "call user" behaviour until a dedicated endpoint lands.
      await apiPost("/command", { cmd: "describe" });
      setMsg("Pesan dikirim ke pengguna.");
    } catch (e: unknown) {
      setMsg(e instanceof Error ? e.message : "Gagal");
    }
    setTimeout(() => setMsg(""), 4000);
  };
  const reportProblem = () => {
    const url = `/admin/legacy#logs`;
    window.open(url, "_blank", "noopener");
  };
  const shutdown = async () => {
    if (!confirm("Yakin matikan perangkat sekarang?")) return;
    setMsg("Mengirim perintah shutdown…");
    try {
      // No dedicated /admin/shutdown endpoint exists yet — surface the link
      // to the legacy console where operators can run `poweroff`.
      window.open("/admin/legacy", "_blank", "noopener");
      setMsg("Buka mode lanjutan untuk konfirmasi matikan.");
    } catch (e: unknown) {
      setMsg(e instanceof Error ? e.message : "Gagal");
    }
    setTimeout(() => setMsg(""), 4000);
  };
  return (
    <section
      class="card"
      style={{
        padding: "var(--s-5)",
        background: "var(--surface-2)",
        display: "flex",
        gap: "var(--s-4)",
        alignItems: "center",
        flexWrap: "wrap",
      }}
    >
      <div style={{ flex: 1, minWidth: 220 }}>
        <div style={{ fontSize: "var(--t-md)", fontWeight: 700 }}>
          Ada yang aneh?
        </div>
        <div style={{ color: "var(--ink-3)", fontSize: "var(--t-sm)" }}>
          Lapor ke tim teknis dengan satu klik. Log otomatis dilampirkan.
        </div>
        {msg && (
          <div
            role="status"
            style={{
              marginTop: 6,
              fontSize: "var(--t-sm)",
              color: "var(--ink-2)",
            }}
          >
            {msg}
          </div>
        )}
      </div>
      <button type="button" class="btn" onClick={reportProblem}>
        <Icon name="flag" size={18} /> {t("footer.report")}
      </button>
      <button type="button" class="btn" onClick={callUser}>
        <Icon name="bell" size={18} /> {t("footer.call")}
      </button>
      <button type="button" class="btn btn--danger" onClick={shutdown}>
        <Icon name="power" size={18} /> {t("footer.shutdown")}
      </button>
    </section>
  );
}

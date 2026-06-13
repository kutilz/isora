import { render } from "preact";
import { useEffect, useState } from "preact/hooks";
import { A11yBar } from "../components/atoms/A11yBar";
import { SkipLink } from "../components/atoms/SkipLink";
import { Hero } from "../components/guide/Hero";
import { StoryboardSection } from "../components/guide/StoryboardSection";
import { HardwareSection } from "../components/guide/HardwareSection";
import { AudioSection } from "../components/guide/AudioSection";
import { PreferencePicker } from "../components/guide/PreferencePicker";
import { t } from "../lib/i18n";
import "../styles/global.css";

function GuideApp() {
  // Sticky bottom CTA shows after the user scrolls past ~30% (handoff §5).
  const [showSticky, setShowSticky] = useState(false);
  useEffect(() => {
    const onScroll = () => {
      const pct =
        window.scrollY /
        Math.max(1, document.documentElement.scrollHeight - window.innerHeight);
      setShowSticky(pct > 0.3);
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <div class="app-shell">
      <SkipLink />
      <A11yBar />

      <main id="main" tabIndex={-1}>
        <Hero />
        <StoryboardSection />
        <HardwareSection />
        <AudioSection />
        <PreferencePicker />

        <section
          style={{
            padding: "var(--s-12) var(--s-5)",
            textAlign: "center",
            background: "var(--bg)",
          }}
        >
          <h2 class="section-title" style={{ marginTop: 0 }}>
            {t("guide.start_setup")}
          </h2>
          <p class="section-sub" style={{ marginLeft: "auto", marginRight: "auto" }}>
            Sudah punya perangkat? Lakukan pengaturan awal — sekitar lima menit.
          </p>
          <a href="/setup" class="btn btn--primary btn--lg">
            {t("guide.start_setup")} →
          </a>
        </section>
      </main>

      {showSticky && (
        <a
          href="/setup"
          class="btn btn--primary btn--lg"
          style={{
            position: "fixed",
            bottom: 16,
            right: 16,
            boxShadow: "var(--shadow-lg)",
            zIndex: 50,
          }}
        >
          {t("guide.start_setup")} →
        </a>
      )}
    </div>
  );
}

render(<GuideApp />, document.getElementById("root")!);

import { AssetImage } from "../atoms/AssetImage";
import { t } from "../../lib/i18n";

/** Hero — top of /guide. Bg gradient + headline + image slot. */
export function Hero() {
  return (
    <section
      style={{
        background:
          "linear-gradient(160deg, var(--surface-2) 0%, var(--bg) 60%)",
        padding: "var(--s-12) var(--s-5)",
      }}
    >
      <div
        class="grid-2"
        style={{
          maxWidth: 1100,
          margin: "0 auto",
          alignItems: "center",
          gap: "var(--s-8)",
        }}
      >
        <div>
          <h1
            style={{
              fontSize: "var(--t-3xl)",
              lineHeight: 1.1,
              margin: "0 0 var(--s-4)",
              letterSpacing: "-0.02em",
            }}
          >
            {t("guide.hero_title")}
          </h1>
          <p
            style={{
              fontSize: "var(--t-md)",
              color: "var(--ink-2)",
              lineHeight: 1.55,
              maxWidth: "52ch",
              margin: "0 0 var(--s-6)",
            }}
          >
            {t("guide.hero_sub")}
          </p>
          <div style={{ display: "flex", gap: "var(--s-3)", flexWrap: "wrap" }}>
            <a href="#audio" class="btn btn--primary btn--lg">
              {t("guide.demo_audio")}
            </a>
            <a href="#hardware" class="btn btn--lg">
              {t("guide.see_hardware")}
            </a>
          </div>
        </div>
        <AssetImage
          name="hero_glasses.jpg"
          alt="Foto AuralAI terpasang di kacamata"
          style={{ width: "100%", borderRadius: "var(--r-lg)", display: "block" }}
          fallback={<HeroGlassesMockup />}
        />
      </div>
    </section>
  );
}

/** SVG fallback for the hero image — mirrors hardware-diagram.jsx GlassesFront. */
function HeroGlassesMockup() {
  return (
    <figure style={{ margin: 0 }}>
      <svg
        viewBox="0 0 480 280"
        style={{ width: "100%", height: "auto" }}
        aria-label="Ilustrasi kacamata dengan modul AuralAI di tangkai kanan"
      >
        <ellipse cx="240" cy="170" rx="44" ry="10" fill="#EAE7DF" />
        <circle cx="170" cy="140" r="58" fill="#F4F2EB" stroke="#3D3D3D" stroke-width="6" />
        <circle cx="310" cy="140" r="58" fill="#F4F2EB" stroke="#3D3D3D" stroke-width="6" />
        <path d="M228 138 Q240 124 252 138" stroke="#3D3D3D" stroke-width="6" fill="none" />
        <path d="M112 140 L60 130" stroke="#3D3D3D" stroke-width="6" stroke-linecap="round" />
        <path d="M368 140 L398 134" stroke="#3D3D3D" stroke-width="6" stroke-linecap="round" />
        <g transform="translate(395,108)">
          <rect width="72" height="58" rx="8" fill="#00635D" stroke="#002D2A" stroke-width="2" />
          <circle cx="14" cy="14" r="7" fill="#141414" />
          <circle cx="14" cy="14" r="4" fill="#3A6E6A" />
          <circle cx="14" cy="14" r="1.5" fill="#fff" />
          <circle cx="32" cy="14" r="1.5" fill="#fff" opacity="0.7" />
          <circle cx="38" cy="14" r="1.5" fill="#fff" opacity="0.7" />
          <circle cx="62" cy="34" r="3" fill="#3DCB6E" />
          <text x="6" y="48" font-family="Inter, sans-serif" font-size="9" font-weight="700" fill="#fff">
            AURALAI
          </text>
        </g>
      </svg>
    </figure>
  );
}

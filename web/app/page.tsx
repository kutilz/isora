import Link from "next/link";
import { t } from "@/lib/i18n";

export default function Home() {
  return (
    <>
      <section className="hero">
        <div className="container">
          <span className="badge">{t.hero.badge}</span>
          <h1>{t.hero.title}</h1>
          <p className="lead">{t.hero.lead}</p>
          <div className="cta-row">
            <Link href="/pair" className="btn btn--primary btn--lg">
              {t.hero.cta_pair}
            </Link>
            <Link href="/docs" className="btn btn--lg">
              {t.hero.cta_docs}
            </Link>
          </div>
        </div>
      </section>

      <section className="section">
        <div className="container">
          <h2>{t.features.title}</h2>
          <div className="grid grid--3" style={{ marginTop: "var(--s-6)" }}>
            {t.features.items.map((f) => (
              <div key={f.title} className="card feature">
                <h3>{f.title}</h3>
                <p>{f.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="section" style={{ background: "var(--surface)" }}>
        <div className="container">
          <h2>{t.how.title}</h2>
          <div className="steps" style={{ marginTop: "var(--s-6)" }}>
            {t.how.steps.map((s, i) => (
              <div key={i} className="step">
                <div className="n" aria-hidden />
                <p style={{ margin: 0, fontSize: "var(--t-md)" }}>{s}</p>
              </div>
            ))}
          </div>
          <div className="cta-row" style={{ marginTop: "var(--s-8)" }}>
            <Link href="/pair" className="btn btn--primary btn--lg">
              {t.hero.cta_pair}
            </Link>
            <Link href="/preview" className="btn btn--lg">
              {t.nav.preview}
            </Link>
          </div>
        </div>
      </section>

      <section className="section">
        <div className="container">
          <div className="card" style={{ background: "var(--accent-soft)", borderColor: "transparent" }}>
            <h2 style={{ marginTop: 0 }}>{t.privacy.title}</h2>
            <p style={{ margin: 0, fontSize: "var(--t-md)", color: "var(--accent-ink)" }}>
              {t.privacy.body}
            </p>
          </div>
        </div>
      </section>
    </>
  );
}

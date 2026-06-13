import Link from "next/link";
import type { DocMeta } from "@/lib/docs";

export default function DocsSidebar({
  docs,
  active,
}: {
  docs: DocMeta[];
  active?: string;
}) {
  return (
    <nav className="docs-side" aria-label="Daftar panduan">
      {docs.map((d) => (
        <Link
          key={d.slug}
          href={`/docs/${d.slug}`}
          className={d.slug === active ? "active" : undefined}
        >
          {d.title}
        </Link>
      ))}
    </nav>
  );
}

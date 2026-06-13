import fs from "node:fs";
import path from "node:path";
import matter from "gray-matter";

const DOCS_DIR = path.join(process.cwd(), "content", "docs");

export type DocMeta = {
  slug: string;
  title: string;
  order: number;
  summary: string;
};

export type Doc = DocMeta & { content: string };

function readDoc(slug: string): Doc {
  const raw = fs.readFileSync(path.join(DOCS_DIR, `${slug}.md`), "utf8");
  const { data, content } = matter(raw);
  return {
    slug,
    title: String(data.title ?? slug),
    order: Number(data.order ?? 99),
    summary: String(data.summary ?? ""),
    content,
  };
}

export function getAllDocs(): DocMeta[] {
  return fs
    .readdirSync(DOCS_DIR)
    .filter((f) => f.endsWith(".md"))
    .map((f) => {
      const { title, order, summary, slug } = readDoc(f.replace(/\.md$/, ""));
      return { title, order, summary, slug };
    })
    .sort((a, b) => a.order - b.order);
}

export function getDoc(slug: string): Doc {
  return readDoc(slug);
}

export function getDocSlugs(): string[] {
  return fs
    .readdirSync(DOCS_DIR)
    .filter((f) => f.endsWith(".md"))
    .map((f) => f.replace(/\.md$/, ""));
}

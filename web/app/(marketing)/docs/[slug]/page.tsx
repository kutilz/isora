import { notFound } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { getAllDocs, getDoc, getDocSlugs } from "@/lib/docs";
import DocsSidebar from "@/components/DocsSidebar";

export function generateStaticParams() {
  return getDocSlugs().map((slug) => ({ slug }));
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  try {
    const doc = getDoc(slug);
    return { title: `${doc.title} — Panduan I-Sora`, description: doc.summary };
  } catch {
    return { title: "Panduan I-Sora" };
  }
}

export default async function DocPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  if (!getDocSlugs().includes(slug)) notFound();

  const doc = getDoc(slug);
  const docs = getAllDocs();

  return (
    <div className="container docs-layout">
      <DocsSidebar docs={docs} active={slug} />
      <article className="prose">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{doc.content}</ReactMarkdown>
      </article>
    </div>
  );
}

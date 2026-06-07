// =============================================================================
// DocViewer.tsx — graphical renderer for the PoC design docs referenced from the
// Test Expectations board. Markdown is bundled at build time (?raw import) and
// rendered with GitHub-flavoured markdown (headings, tables, code, lists) so the
// docs open in a new tab as a styled page instead of raw text.
// =============================================================================
import { useParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { AppShell } from "../components/AppShell";
import productionDesignNotes from "../content/docs/production-design-notes.md?raw";
import fitGap from "../content/docs/fit-gap.md?raw";

interface DocEntry {
  title: string;
  crumb: string;
  subtitle: string;
  source: string;
  content: string;
}

const DOCS: Record<string, DocEntry> = {
  "production-design-notes": {
    title: "Production Design Notes",
    crumb: "Production Design Notes",
    subtitle: "Hardening and design considerations for taking this PoC to production.",
    source: "docs/production-design-notes.md",
    content: productionDesignNotes,
  },
  "fit-gap": {
    title: "Fit / Gap Analysis",
    crumb: "Fit / Gap",
    subtitle: "Where the PoC meets the target architecture and what remains for a production security baseline.",
    source: "docs/fit-gap.md",
    content: fitGap,
  },
};

export function DocViewer() {
  const { slug } = useParams<{ slug: string }>();
  const doc = slug ? DOCS[slug] : undefined;

  if (!doc) {
    return (
      <AppShell
        hero={{ crumb: "Docs", title: "Document not found", subtitle: "The requested document is not available." }}
      >
        <main className="page">
          <div className="panel">
            <p className="sub">No document matches “{slug}”. Available: production-design-notes, fit-gap.</p>
          </div>
        </main>
      </AppShell>
    );
  }

  return (
    <AppShell
      hero={{ crumb: doc.crumb, title: doc.title, subtitle: doc.subtitle, tags: [`source: ${doc.source}`] }}
    >
      <main className="page">
        <div className="panel doc-prose">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{doc.content}</ReactMarkdown>
        </div>
      </main>
    </AppShell>
  );
}

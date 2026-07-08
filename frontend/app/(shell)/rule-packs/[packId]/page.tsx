"use client";

import { Code } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { packDocumentMarkdown, type RulePackBrowseSummary } from "@/lib/rule-packs";

// Rule-pack document page (bead pydexpi-datalog-1-2c5.3). A rule pack IS a
// markdown document (bead pydexpi-datalog-1-1vd): this page renders its
// canonical markdown read-only, with a raw-source toggle. Fenced
// souffle-datalog blocks keep the collapsed-disclosure treatment.
export default function RulePackDetailPage() {
  const params = useParams<{ packId: string }>();
  const packId = params.packId;
  const [packs, setPacks] = useState<RulePackBrowseSummary[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [showSource, setShowSource] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setPacks(null);
    setListError(null);
    fetch("/api/rule-packs")
      .then(async (res) => {
        if (!res.ok) throw new Error(`Rule pack list failed (${res.status})`);
        const body = (await res.json()) as { packs?: RulePackBrowseSummary[] };
        if (!cancelled) setPacks(body.packs ?? []);
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setListError(error instanceof Error ? error.message : "Rule pack list failed");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const pack = useMemo(
    () => packs?.find((entry) => entry.pack_id === packId) ?? null,
    [packs, packId],
  );

  return (
    <div className="shell-page shell-page-wide">
      <nav className="rule-pack-breadcrumb" aria-label="Breadcrumb">
        <Link href="/rule-packs">Rule Packs</Link>
        <span aria-hidden="true">›</span>
        <span className="rule-pack-breadcrumb-current">{pack ? pack.title : packId}</span>
      </nav>

      {listError && (
        <div className="rule-pack-error" data-testid="rule-pack-list-error">
          <p>{listError}</p>
        </div>
      )}
      {!listError && packs === null && <p className="shell-page-empty">Loading…</p>}
      {!listError && packs !== null && pack === null && (
        <p className="shell-page-empty" data-testid="rule-pack-not-found">
          No rule pack named &ldquo;{packId}&rdquo; exists.
        </p>
      )}

      {pack && (
        <>
          <dl className="rule-pack-meta-strip" data-testid="rule-pack-meta">
            <div>
              <dt>Source</dt>
              <dd>System</dd>
            </div>
            <div>
              <dt>Language</dt>
              <dd>Souffle Datalog</dd>
            </div>
            <div>
              <dt>Version</dt>
              <dd>{pack.version}</dd>
            </div>
            <div>
              <dt>Rules</dt>
              <dd>{pack.rules.length}</dd>
            </div>
            <div>
              <dt>Standing</dt>
              <dd>{pack.authoritative ? "Authoritative" : "Demonstration"}</dd>
            </div>
          </dl>
          <p className="rule-pack-trust-notice">{pack.trust_notice}</p>

          <section className="rule-pack-doc" data-testid="rule-pack-doc">
            <header className="rule-pack-doc-toolbar">
              <span>Read-only</span>
              <button
                type="button"
                data-testid="rule-pack-source-toggle"
                aria-pressed={showSource}
                aria-label={showSource ? "Show rendered document" : "Show markdown source"}
                onClick={() => setShowSource((value) => !value)}
              >
                <Code size={14} aria-hidden="true" />
              </button>
            </header>
            {showSource ? (
              <pre className="rule-pack-doc-source" data-testid="rule-pack-doc-source">
                <code>{pack.markdown}</code>
              </pre>
            ) : (
              <div className="rule-pack-markdown" data-testid="rule-pack-doc-rendered">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    pre: ({ children }) => <>{children}</>,
                    code: (props) => <MarkdownCode {...props} />,
                  }}
                >
                  {packDocumentMarkdown(pack.markdown)}
                </ReactMarkdown>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}

function MarkdownCode({ className, children }: { className?: string; children?: React.ReactNode }) {
  const language = /language-([\w-]+)/.exec(className ?? "")?.[1];
  if (language === "souffle-datalog") {
    // Executable logic keeps the collapsed-disclosure treatment: the
    // engineer-readable document stays readable, exact Datalog on demand.
    return (
      <details data-testid="rule-logic-disclosure">
        <summary>Exact Datalog (Souffle)</summary>
        <pre className="datalog-syntax">
          <code>{children}</code>
        </pre>
      </details>
    );
  }
  if (language) {
    return (
      <pre className="rule-pack-doc-source">
        <code className={className}>{children}</code>
      </pre>
    );
  }
  return <code className={className}>{children}</code>;
}

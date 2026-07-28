"use client";

import { Plus, Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  filterRulePacks,
  packContentsLabel,
  packSourceLabel,
  type RulePackBrowseSummary,
} from "@/lib/rule-packs";

// Session-independent rule-pack browse page (bead pydexpi-datalog-1-2c5.3 /
// 1nox.3). Searchable table of bundled + authored packs; New Pack creates an
// advisory-first authored pack via POST /api/rule-packs (no compile-on-upload).
export default function RulePacksPage() {
  const router = useRouter();
  const [packs, setPacks] = useState<RulePackBrowseSummary[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [refreshToken, setRefreshToken] = useState(0);
  const [createOpen, setCreateOpen] = useState(false);
  const [markdown, setMarkdown] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

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
  }, [refreshToken]);

  const filteredPacks = useMemo(() => filterRulePacks(packs ?? [], query), [packs, query]);

  async function submitCreatedPack() {
    setCreating(true);
    setCreateError(null);
    try {
      const res = await fetch("/api/rule-packs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ markdown }),
      });
      const body = (await res.json()) as {
        pack?: { pack_id?: string };
        error?: { message?: string };
        detail?: { error?: { message?: string } };
      };
      if (!res.ok) {
        const message =
          body.error?.message ?? body.detail?.error?.message ?? `Create failed (${res.status})`;
        throw new Error(message);
      }
      const packId = body.pack?.pack_id;
      setCreateOpen(false);
      setMarkdown("");
      setRefreshToken((token) => token + 1);
      if (packId) router.push(`/rule-packs/${packId}`);
    } catch (error: unknown) {
      setCreateError(error instanceof Error ? error.message : "Create failed");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="shell-page shell-page-wide">
      <div className="rule-pack-page-header">
        <div>
          <h1 className="shell-page-title">Rule Packs</h1>
          <p className="shell-page-empty">
            Browse bundled and authored rule packs. Advisory guidance and executable rules are
            listed separately; attaching a pack to a chat still happens from the Rule Packs button
            next to the composer.
          </p>
        </div>
        <Button
          type="button"
          data-testid="rule-pack-new"
          onClick={() => {
            setCreateError(null);
            setCreateOpen(true);
          }}
        >
          <Plus size={16} aria-hidden="true" />
          New Pack
        </Button>
      </div>

      <div className="rule-pack-search-row">
        <label className="pid-search">
          <Search size={14} aria-hidden="true" />
          <span className="sr-only">Search rule packs</span>
          <input
            type="text"
            placeholder="Search rule packs…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
      </div>

      {listError && (
        <div className="rule-pack-error" data-testid="rule-pack-list-error">
          <p>{listError}</p>
          <button type="button" onClick={() => setRefreshToken((token) => token + 1)}>
            Retry
          </button>
        </div>
      )}

      {!listError && (
        <table className="rule-pack-table" data-testid="rule-pack-table">
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col">Contents</th>
              <th scope="col">Language</th>
              <th scope="col">Version</th>
              <th scope="col">Source</th>
            </tr>
          </thead>
          <tbody>
            {packs === null && (
              <tr>
                <td className="rule-pack-table-empty" colSpan={5}>
                  Loading…
                </td>
              </tr>
            )}
            {packs !== null && filteredPacks.length === 0 && (
              <tr>
                <td className="rule-pack-table-empty" colSpan={5}>
                  No rule packs found.
                </td>
              </tr>
            )}
            {filteredPacks.map((pack) => (
              <tr
                key={pack.pack_id}
                data-testid="rule-pack-row"
                data-pack-id={pack.pack_id}
                data-source={pack.source ?? "system"}
                tabIndex={0}
                onClick={() => router.push(`/rule-packs/${pack.pack_id}`)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    router.push(`/rule-packs/${pack.pack_id}`);
                  }
                }}
              >
                <td className="rule-pack-table-name">{pack.title}</td>
                <td data-testid="rule-pack-contents">{packContentsLabel(pack)}</td>
                <td>{pack.rules.length > 0 ? "Souffle Datalog" : "Advisory"}</td>
                <td>{pack.version}</td>
                <td data-testid="rule-pack-source">{packSourceLabel(pack)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="sm:max-w-2xl" data-testid="rule-pack-create-dialog">
          <DialogHeader>
            <DialogTitle>New rule pack</DialogTitle>
            <DialogDescription>
              Paste markdown with YAML frontmatter. It is stored immediately as a User pack
              (advisory-first). Executable trust requires explicit promotion later.
            </DialogDescription>
          </DialogHeader>
          <textarea
            className="rule-pack-create-textarea"
            data-testid="rule-pack-create-markdown"
            rows={16}
            spellCheck={false}
            placeholder={`---\npack_id: my-pack\nversion: 1\ntitle: My pack\nauthoritative: false\ntrust_notice: Advisory only.\n---\n\n# My pack\n\n## Guidance\n\nWrite advisory guidance here.`}
            value={markdown}
            onChange={(event) => setMarkdown(event.target.value)}
          />
          {createError && (
            <p className="rule-pack-action-error" data-testid="rule-pack-create-error">
              {createError}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button
              type="button"
              data-testid="rule-pack-create-submit"
              disabled={creating || markdown.trim() === ""}
              onClick={() => void submitCreatedPack()}
            >
              {creating ? "Creating…" : "Create pack"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

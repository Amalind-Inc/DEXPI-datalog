"use client";

import { Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { filterRulePacks, packContentsLabel, type RulePackBrowseSummary } from "@/lib/rule-packs";

// Session-independent rule-pack browse page (bead pydexpi-datalog-1-2c5.3).
// A searchable table of all bundled rule packs (MikeOSS Workflows-style);
// each row navigates to the pack's document page at /rule-packs/[id].
// Attaching a pack to a chat still happens from the composer's Rule Packs
// trigger.
export default function RulePacksPage() {
  const router = useRouter();
  const [packs, setPacks] = useState<RulePackBrowseSummary[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [refreshToken, setRefreshToken] = useState(0);

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

  return (
    <div className="shell-page shell-page-wide">
      <h1 className="shell-page-title">Rule Packs</h1>
      <p className="shell-page-empty">
        Browse bundled and authored rule packs. Advisory guidance and executable
        rules are listed separately; attaching a pack to a chat still happens from
        the Rule Packs button next to the composer.
      </p>

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
                <td>System</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

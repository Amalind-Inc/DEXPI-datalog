export type RuleRestatement = {
  kind: string;
  plain_language_meaning: string;
};

export type RuleExecutableLogic = {
  kind: string;
  language: string;
  content: string;
  inspectable: boolean;
  editable: boolean;
  disclosure: string;
};

export type AdvisoryPackGuidance = {
  kind: string;
  title: string;
  body: string;
};

export type RulePackRule = {
  rule_id: string;
  title: string;
  outcomes: string[];
  restatement: RuleRestatement;
  executable_logic: RuleExecutableLogic;
};

export type RulePackSummary = {
  pack_id: string;
  version: number;
  title: string;
  authoritative: boolean;
  trust_notice: string;
  loaded: boolean;
  source?: "system" | "user";
  advisory_guidance: AdvisoryPackGuidance[];
  rules: RulePackRule[];
};

export function packSourceLabel(pack: { source?: "system" | "user" }): "System" | "User" {
  return pack.source === "user" ? "User" : "System";
}

export type RulePackListResponse = {
  session_id: string;
  packs: RulePackSummary[];
};

export type RulePackBrowseSummary = Omit<RulePackSummary, "loaded"> & {
  /** Canonical markdown source of the pack (bead pydexpi-datalog-1-1vd). */
  markdown: string;
};

export type RulePackBrowseListResponse = {
  packs: RulePackBrowseSummary[];
};

/** Filter packs by pack title, advisory guidance, rule titles, and restatement text. */
export function filterRulePacks(
  packs: RulePackBrowseSummary[],
  query: string,
): RulePackBrowseSummary[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return packs;
  return packs.filter(
    (pack) =>
      pack.title.toLowerCase().includes(needle) ||
      (pack.advisory_guidance ?? []).some(
        (section) =>
          section.title.toLowerCase().includes(needle) ||
          section.body.toLowerCase().includes(needle),
      ) ||
      pack.rules.some(
        (rule) =>
          rule.title.toLowerCase().includes(needle) ||
          rule.restatement.plain_language_meaning.toLowerCase().includes(needle),
      ),
  );
}

/**
 * Compact browse-table label distinguishing advisory guidance from rules.
 */
export function packContentsLabel(pack: {
  advisory_guidance?: AdvisoryPackGuidance[];
  rules: RulePackRule[];
}): string {
  const guidanceCount = pack.advisory_guidance?.length ?? 0;
  const ruleCount = pack.rules.length;
  if (guidanceCount === 0 && ruleCount === 0) return "Empty";
  if (guidanceCount === 0) return `${ruleCount} rule${ruleCount === 1 ? "" : "s"}`;
  if (ruleCount === 0) {
    return `${guidanceCount} guidance`;
  }
  return `${guidanceCount} guidance · ${ruleCount} rule${ruleCount === 1 ? "" : "s"}`;
}

/** Remove the leading YAML frontmatter block from pack markdown, if present. */
export function stripFrontmatter(markdown: string): string {
  const lines = markdown.split("\n");
  if (lines[0]?.trim() !== "---") return markdown;
  for (let index = 1; index < lines.length; index += 1) {
    if (lines[index].trim() === "---") {
      let start = index + 1;
      while (start < lines.length && lines[start].trim() === "") start += 1;
      return lines.slice(start).join("\n");
    }
  }
  return markdown;
}

/**
 * Markdown ready for rendered display: frontmatter removed and rule-id
 * heading anchors (`## Title {#rule_id}`) stripped -- the anchors are parser
 * metadata, not document prose.
 */
export function packDocumentMarkdown(markdown: string): string {
  return stripFrontmatter(markdown)
    .split("\n")
    .map((line) =>
      /^#{1,6}\s/.test(line) ? line.replace(/\s*\{#[A-Za-z0-9_.-]+\}\s*$/, "") : line,
    )
    .join("\n");
}

import assert from "node:assert/strict";
import test from "node:test";
import {
  filterRulePacks,
  packDocumentMarkdown,
  stripFrontmatter,
  type RulePackBrowseSummary,
} from "./rule-packs.ts";

function pack(overrides: Partial<RulePackBrowseSummary> = {}): RulePackBrowseSummary {
  return {
    pack_id: "demo-pack",
    version: 1,
    title: "Demo Pack",
    authoritative: false,
    trust_notice: "Demo trust notice",
    markdown: "---\npack_id: demo-pack\n---\n\n# Demo Pack\n",
    rules: [
      {
        rule_id: "r1",
        title: "Rule One",
        outcomes: ["satisfied", "violated", "indeterminate"],
        restatement: { kind: "plain", plain_language_meaning: "Checks X." },
        executable_logic: {
          kind: "datalog",
          language: "souffle_datalog",
          content: "rule1(X) :- foo(X).",
          inspectable: true,
          editable: false,
          disclosure: "collapsed",
        },
      },
    ],
    ...overrides,
  };
}

test("filterRulePacks: empty query keeps every pack", () => {
  const packs = [pack(), pack({ pack_id: "other", title: "Other Pack" })];
  assert.deepEqual(filterRulePacks(packs, "  "), packs);
});

test("filterRulePacks: matches pack title case-insensitively", () => {
  const packs = [pack(), pack({ pack_id: "other", title: "Other Pack" })];
  const filtered = filterRulePacks(packs, "demo");
  assert.deepEqual(
    filtered.map((entry) => entry.pack_id),
    ["demo-pack"],
  );
});

test("filterRulePacks: matches rule title and restatement text", () => {
  const packs = [
    pack(),
    pack({
      pack_id: "other",
      title: "Other Pack",
      rules: [
        {
          ...pack().rules[0],
          rule_id: "r2",
          title: "Rule Two",
          restatement: { kind: "plain", plain_language_meaning: "Checks Y." },
        },
      ],
    }),
  ];
  assert.deepEqual(
    filterRulePacks(packs, "Checks Y").map((entry) => entry.pack_id),
    ["other"],
  );
  assert.deepEqual(
    filterRulePacks(packs, "rule two").map((entry) => entry.pack_id),
    ["other"],
  );
  assert.deepEqual(filterRulePacks(packs, "nonexistent"), []);
});

test("stripFrontmatter: removes the YAML frontmatter block", () => {
  const markdown = "---\npack_id: demo\nversion: 1\n---\n\n# Title\n\nBody text.\n";
  assert.equal(stripFrontmatter(markdown), "# Title\n\nBody text.\n");
});

test("stripFrontmatter: returns text unchanged when no frontmatter exists", () => {
  const markdown = "# Title\n\nBody text.\n";
  assert.equal(stripFrontmatter(markdown), markdown);
});

test("packDocumentMarkdown: strips frontmatter and heading id anchors", () => {
  const markdown = "---\npack_id: demo\n---\n\n# Title\n\n## Rule One {#rule_one}\n\nProse.\n";
  assert.equal(packDocumentMarkdown(markdown), "# Title\n\n## Rule One\n\nProse.\n");
});

import assert from "node:assert/strict";
import test from "node:test";
import {
  filterRulePacks,
  packContentsLabel,
  packDocumentMarkdown,
  packSourceLabel,
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
    advisory_guidance: [],
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

test("filterRulePacks: matches advisory guidance text", () => {
  const packs = [
    pack(),
    pack({
      pack_id: "epa",
      title: "EPA highlights",
      advisory_guidance: [
        {
          kind: "advisory_pack_guidance",
          title: "Isolation expectations",
          body: "Confirm isolation valves around major equipment.",
        },
      ],
      rules: [],
    }),
  ];
  assert.deepEqual(
    filterRulePacks(packs, "isolation valves").map((entry) => entry.pack_id),
    ["epa"],
  );
});

test("packContentsLabel: distinguishes advisory guidance from rules", () => {
  assert.equal(packContentsLabel(pack()), "1 rule");
  assert.equal(
    packContentsLabel(
      pack({
        advisory_guidance: [
          { kind: "advisory_pack_guidance", title: "A", body: "B" },
        ],
        rules: [],
      }),
    ),
    "1 guidance",
  );
  assert.equal(
    packContentsLabel(
      pack({
        advisory_guidance: [
          { kind: "advisory_pack_guidance", title: "A", body: "B" },
        ],
      }),
    ),
    "1 guidance · 1 rule",
  );
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

test("packSourceLabel: maps source provenance", () => {
  assert.equal(packSourceLabel({}), "System");
  assert.equal(packSourceLabel({ source: "system" }), "System");
  assert.equal(packSourceLabel({ source: "user" }), "User");
});

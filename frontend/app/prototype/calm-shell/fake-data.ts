// PROTOTYPE fake data — shared across variants so the comparison is about
// layout, not content. Nothing here is wired to a real session.

export type FakeSession = {
  id: string;
  title: string;
  fileName: string;
  updatedAt: string;
  status: "in review" | "blocked" | "approved";
};

export const fakeSessions: FakeSession[] = [
  { id: "s1", title: "C01 Reference P&ID", fileName: "C01V04-VER.EX01.xml", updatedAt: "2m ago", status: "blocked" },
  { id: "s2", title: "E06 Pump + HX skid", fileName: "E06V01-VER.EX01.xml", updatedAt: "1h ago", status: "in review" },
  { id: "s3", title: "P14 Utility header", fileName: "P14V02-VER.EX01.xml", updatedAt: "yesterday", status: "approved" },
];

export type FakeRulePack = {
  id: string;
  name: string;
  description: string;
  ruleCount: number;
  tag: "core" | "client" | "draft";
};

export const fakeRulePacks: FakeRulePack[] = [
  { id: "rp1", name: "DEXPI Core", description: "Baseline topology and tag-format checks", ruleCount: 42, tag: "core" },
  { id: "rp2", name: "Client: Meridian Energy", description: "Line-list numbering and insulation call-outs", ruleCount: 18, tag: "client" },
  { id: "rp3", name: "Draft: Relief Valve Sizing", description: "Under construction, not yet reviewed", ruleCount: 6, tag: "draft" },
];

export type FakeTurn = {
  id: string;
  step: number;
  kind: "assistant" | "consent";
  title: string;
  body: string;
  evidence?: string[];
};

export const fakeTurns: FakeTurn[] = [
  {
    id: "t1",
    step: 1,
    kind: "assistant",
    title: "Checked tag format on 214 equipment units",
    body: "211 of 214 tags match the DEXPI Core naming pattern. 3 exceptions found on the utility header, all missing an area code prefix.",
    evidence: ["PU-1101", "PU-1102", "TK-2201"],
  },
  {
    id: "t2",
    step: 2,
    kind: "assistant",
    title: "Cross-checked line list against source-document connectivity",
    body: "All 58 process lines resolve to a source and destination unit. No dangling ends detected.",
    evidence: ["L-100-6\"-CS", "L-101-4\"-CS"],
  },
  {
    id: "t3",
    step: 3,
    kind: "consent",
    title: "Proposed fix: rename 3 tags to add area code",
    body: "PU-1101 → PU-11-1101, PU-1102 → PU-11-1102, TK-2201 → TK-22-2201. This edits the source DEXPI file's tag attributes only — no topology changes.",
    evidence: ["PU-1101", "PU-1102", "TK-2201"],
  },
];

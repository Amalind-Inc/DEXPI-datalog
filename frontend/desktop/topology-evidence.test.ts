import assert from "node:assert/strict";
import test from "node:test";

import { boundedTopologyEvidence } from "./topology-evidence.ts";

const nodes = [
  { id: "pump", display_name: "P-4713", category: "equipment" },
  { id: "pump-n2", display_name: "P-4713 / N-2", category: "nozzle" },
  { id: "pipe", display_name: "Pipe", category: "piping" },
  { id: "segment", display_name: "Line 47132 (segment)", category: "piping" },
  { id: "hex-n1", display_name: "H-1009 / N-1", category: "nozzle" },
  { id: "hex", display_name: "H-1009", category: "equipment" },
];

const edges = [
  { source_id: "pump", target_id: "pump-n2", relationship: "nozzles" },
  { source_id: "pipe", target_id: "pump-n2", relationship: "sourceItem" },
  { source_id: "pipe", target_id: "hex-n1", relationship: "targetItem" },
  { source_id: "segment", target_id: "pump-n2", relationship: "sourceItem" },
  { source_id: "segment", target_id: "hex-n1", relationship: "targetItem" },
  { source_id: "segment", target_id: "pipe", relationship: "connections" },
  { source_id: "hex", target_id: "hex-n1", relationship: "nozzles" },
];

const topology = { nodes, edges };
const deepChainNodes = Array.from({ length: 7 }, (_, index) => ({
  id: `chain-${index}`,
  display_name: `N-${index}`,
  category: "piping",
}));

const deepChainEdges = deepChainNodes.slice(0, -1).map((node, index) => ({
  source_id: node.id,
  target_id: deepChainNodes[index + 1].id,
  relationship: "connections",
}));

test("bounded traversal marks partial evidence when the hop limit is reached", () => {
  const result = boundedTopologyEvidence(
    { nodes: deepChainNodes, edges: deepChainEdges },
    "N-0 downstream path",
  );

  assert.equal(result.diagnostics[0]?.code, "partial_evidence");
  assert.match(result.diagnostics[0]?.message ?? "", /hop limit/);
  assert.equal(result.entities.length, 5);
  assert.equal(result.uncertainty, "Evidence is bounded and may omit additional topology context.");
});
test("bounded traversal keeps an exact hop-boundary result complete", () => {
  const result = boundedTopologyEvidence(
    { nodes: deepChainNodes.slice(0, 5), edges: deepChainEdges.slice(0, 4) },
    "N-0 downstream path",
  );

  assert.deepEqual(result.diagnostics, []);
  assert.equal(result.uncertainty, null);
  assert.equal(result.entities.length, 5);
});
test("bounded traversal marks partial evidence when the entity limit is reached", () => {
  const nodesAtLimit = Array.from({ length: 33 }, (_, index) => ({
    id: `entity-${index}`,
    display_name: `N-${index}`,
    category: "piping",
  }));
  const edgesAtLimit = [
    {
      source_id: nodesAtLimit[0].id,
      target_id: nodesAtLimit[1].id,
      relationship: "connections",
    },
    ...nodesAtLimit.slice(2, 32).map((node) => ({
      source_id: nodesAtLimit[1].id,
      target_id: node.id,
      relationship: "connections",
    })),
    {
      source_id: nodesAtLimit[31].id,
      target_id: nodesAtLimit[32].id,
      relationship: "connections",
    },
  ];

  const result = boundedTopologyEvidence(
    { nodes: nodesAtLimit, edges: edgesAtLimit },
    "N-0 downstream path",
  );

  assert.equal(result.diagnostics[0]?.code, "partial_evidence");
  assert.match(result.diagnostics[0]?.message ?? "", /entity limit/);
  assert.equal(result.entities.length, 32);
});

test("endpoint claims return both directed path endpoints", () => {
  const result = boundedTopologyEvidence(topology, "P-4713 downstream path");

  assert.deepEqual(result.diagnostics, []);
  assert.deepEqual(
    result.relationships
      .filter((edge) => edge.relationship === "sourceItem" || edge.relationship === "targetItem")
      .map((edge) => [edge.relationship, edge.source_id, edge.target_id]),
    [
      ["sourceItem", "pipe", "pump-n2"],
      ["targetItem", "pipe", "hex-n1"],
      ["sourceItem", "segment", "pump-n2"],
      ["targetItem", "segment", "hex-n1"],
    ],
  );
  assert.deepEqual(
    result.entities.map((entity) => entity.id),
    ["pump", "pump-n2", "pipe", "segment", "hex-n1", "hex"],
  );
  assert.ok(result.citations.includes("pump-n2"));
  assert.ok(result.citations.includes("hex-n1"));
});

test("an absent identifier remains a bounded no-match instead of a global absence claim", () => {
  const result = boundedTopologyEvidence(topology, "P-101 downstream path");

  assert.deepEqual(result.entities, []);
  assert.deepEqual(result.relationships, []);
  assert.deepEqual(result.citations, []);
  assert.deepEqual(result.diagnostics, [
    {
      code: "no_matching_evidence",
      message: "No bounded topology evidence matched the requested identifiers.",
    },
  ]);
  assert.equal(result.uncertainty, "Evidence is insufficient for this question.");
});

test("an ambiguous class claim retains bounded topology context for clarification", () => {
  const result = boundedTopologyEvidence(topology, "nozzle");

  assert.deepEqual(result.diagnostics, []);
  assert.ok(result.entities.some((entity) => entity.display_name === "P-4713 / N-2"));
  assert.ok(result.entities.some((entity) => entity.display_name === "H-1009 / N-1"));
});

export type TopologyEvidenceDiagnostic = {
  code: "no_matching_evidence" | "partial_evidence";
  message: string;
};

export type BoundedTopologyEvidence = {
  artifactId: "topology";
  claim: string;
  entities: Array<Record<string, unknown>>;
  relationships: Array<Record<string, unknown>>;
  citations: string[];
  sourceScopeIds: string[];
  diagnostics: TopologyEvidenceDiagnostic[];
  uncertainty: string | null;
};

type TopologyRecord = Record<string, unknown>;

const MAX_ANCHORS = 12;
const MAX_ENTITIES = 32;
const MAX_RELATIONSHIPS = 32;
const MAX_HOPS = 4;

// These are the relation fields that can carry a bounded process-piping path.
// In particular, sourceItem and targetItem remain directed in the returned
// edge objects even though closure discovery considers both endpoints.
const PATH_RELATIONSHIPS = new Set([
  "connections",
  "items",
  "nodes",
  "nozzles",
  "pipingNetworkSegments",
  "segments",
  "sourceItem",
  "sourceNode",
  "targetItem",
  "targetNode",
]);

export function boundedTopologyEvidence(payload: unknown, claim: string): BoundedTopologyEvidence {
  const panel = isRecord(payload) ? payload : {};
  const topology = isRecord(panel.topology_view) ? panel.topology_view : panel;
  const nodes = Array.isArray(topology.nodes) ? topology.nodes.filter(isRecord) : [];
  const edges = Array.isArray(topology.edges) ? topology.edges.filter(isRecord) : [];
  const nodeIds = new Set(nodes.map(readId).filter((id): id is string => id !== null));
  const identifiers = extractIdentifiers(claim);
  const matchingNodeIds = identifiers.length
    ? nodes
        .filter((node) => identifiers.some((identifier) => recordMentions(node, identifier)))
        .map(readId)
        .filter((id): id is string => id !== null)
    : nodes.map(readId).filter((id): id is string => id !== null);
  const matchedIds = matchingNodeIds.slice(0, MAX_ANCHORS);

  if (!matchedIds.length) return noMatchingEvidence(claim);

  const partialReasons: string[] = [];
  if (identifiers.length > MAX_ANCHORS || matchingNodeIds.length > MAX_ANCHORS) {
    partialReasons.push("anchor limit");
  }

  const selectedNodeIds = new Set(matchedIds);
  const selectedEdgeIndexes = new Set<number>();
  let frontier = new Set(matchedIds);
  let reachedHopLimit = false;
  let reachedEntityLimit = false;

  for (let hop = 0; hop < MAX_HOPS && selectedNodeIds.size < MAX_ENTITIES; hop += 1) {
    const nextFrontier = new Set<string>();
    for (const [index, edge] of edges.entries()) {
      if (selectedEdgeIndexes.size >= MAX_RELATIONSHIPS) break;
      if (!isPathRelationship(edge)) continue;
      const endpoints = edgeEndpointIds(edge).filter((id) => nodeIds.has(id));
      if (!endpoints.some((id) => frontier.has(id))) continue;

      selectedEdgeIndexes.add(index);
      for (const endpoint of endpoints) {
        if (!selectedNodeIds.has(endpoint) && selectedNodeIds.size < MAX_ENTITIES) {
          selectedNodeIds.add(endpoint);
          nextFrontier.add(endpoint);
        } else if (!selectedNodeIds.has(endpoint)) {
          reachedEntityLimit = true;
        }
      }
    }
    frontier = nextFrontier;
    if (!frontier.size) break;
  }

  if (
    frontier.size &&
    selectedNodeIds.size < MAX_ENTITIES &&
    edges.some(
      (edge, index) =>
        !selectedEdgeIndexes.has(index) &&
        isPathRelationship(edge) &&
        edgeEndpointIds(edge).some((id) => frontier.has(id)),
    )
  ) {
    reachedHopLimit = true;
  }
  if (
    frontier.size &&
    selectedNodeIds.size >= MAX_ENTITIES &&
    edges.some(
      (edge, index) =>
        !selectedEdgeIndexes.has(index) &&
        isPathRelationship(edge) &&
        edgeEndpointIds(edge).some((id) => frontier.has(id)),
    )
  ) {
    reachedEntityLimit = true;
  }

  if (reachedHopLimit) partialReasons.push("hop limit");
  if (reachedEntityLimit) partialReasons.push("entity limit");

  const relationships = edges.filter((_edge, index) => selectedEdgeIndexes.has(index));
  const entities = nodes.filter((node) => {
    const id = readId(node);
    return id !== null && selectedNodeIds.has(id);
  });
  const endpointIds = relationships.flatMap(edgeEndpointIds);
  const omittedReachableRelationship =
    selectedEdgeIndexes.size >= MAX_RELATIONSHIPS &&
    edges.some(
      (edge, index) =>
        !selectedEdgeIndexes.has(index) &&
        isPathRelationship(edge) &&
        edgeEndpointIds(edge).some((id) => selectedNodeIds.has(id)),
    );
  if (omittedReachableRelationship) partialReasons.push("relationship limit");

  const allCitationIds = Array.from(new Set([...matchedIds, ...endpointIds]));
  const citations = allCitationIds.slice(0, MAX_ENTITIES);
  if (allCitationIds.length > MAX_ENTITIES) partialReasons.push("citation limit");
  const diagnostics: TopologyEvidenceDiagnostic[] = partialReasons.length
    ? [
        {
          code: "partial_evidence",
          message: `Bounded topology evidence is partial (${partialReasons.join(", ")}).`,
        },
      ]
    : [];

  return {
    artifactId: "topology",
    claim,
    entities,
    relationships,
    citations,
    sourceScopeIds: citations,
    diagnostics,
    uncertainty: partialReasons.length
      ? "Evidence is bounded and may omit additional topology context."
      : null,
  };
}

function noMatchingEvidence(claim: string): BoundedTopologyEvidence {
  return {
    artifactId: "topology",
    claim,
    entities: [],
    relationships: [],
    citations: [],
    sourceScopeIds: [],
    diagnostics: [
      {
        code: "no_matching_evidence",
        message: "No bounded topology evidence matched the requested identifiers.",
      },
    ],
    uncertainty: "Evidence is insufficient for this question.",
  };
}

function extractIdentifiers(claim: string): string[] {
  return Array.from(
    new Set(claim.match(/[A-Za-z]+[-_]?\d+(?:[\\/._-][A-Za-z0-9]+)*/g) ?? []),
  ).slice(0, MAX_ANCHORS);
}

function recordMentions(record: TopologyRecord, identifier: string): boolean {
  const searchable = normalize(JSON.stringify(record));
  return searchable.includes(normalize(identifier));
}

function isPathRelationship(edge: TopologyRecord): boolean {
  const relationship =
    edge.relationship ?? edge.attr_name ?? readNestedAttribute(edge, "attr_name");
  return typeof relationship === "string" && PATH_RELATIONSHIPS.has(relationship);
}

function readNestedAttribute(edge: TopologyRecord, name: string): unknown {
  const attributes = edge.attributes;
  return isRecord(attributes) ? attributes[name] : undefined;
}

function readId(value: TopologyRecord): string | null {
  if (typeof value.id === "string") return value.id;
  if (typeof value.node_id === "string") return value.node_id;
  return null;
}

function edgeEndpointIds(edge: TopologyRecord): string[] {
  return [edge.source_id, edge.target_id, edge.source, edge.target, edge.from, edge.to].filter(
    (value): value is string => typeof value === "string",
  );
}

function normalize(value: string): string {
  return value.toLowerCase().replace(/\s+/g, "");
}

function isRecord(value: unknown): value is TopologyRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

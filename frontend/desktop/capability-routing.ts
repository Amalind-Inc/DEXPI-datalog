import { createHash } from "node:crypto";

import type {
  EvidenceRequest,
  RuleCheckRequest,
  RunGovernedPiIsolatedCommand,
} from "./pi-turn-adapter.ts";

export type PreparedPosture = "inspect" | "verify" | "review";
export type CapabilityMode = "inspection" | "chat" | undefined;

const HOST_POLICY_MANIFEST = {
  id: "portlog-host-policy",
  version: "1",
  rules: [
    "workspace-read-only",
    "portlog-authority-from-capability-result",
    "isolated-command-fail-closed",
  ],
} as const;

export const PORTLOG_HOST_POLICY = Object.freeze({
  id: HOST_POLICY_MANIFEST.id,
  version: HOST_POLICY_MANIFEST.version,
  digest: `sha256:${createHash("sha256").update(JSON.stringify(HOST_POLICY_MANIFEST)).digest("hex")}`,
});

export function createPortLogToolProfile(options: {
  hostEvidence: boolean;
  hostRules: boolean;
  isolatedExecution: boolean;
}) {
  const tools = [
    "read",
    ...(options.hostEvidence ? ["portlog_evidence"] : []),
    ...(options.hostRules ? ["portlog_rule_check"] : []),
    ...(options.isolatedExecution ? ["portlog_isolated_command"] : []),
  ];
  const manifest = { id: "pi-portlog", version: "1", tools };
  return Object.freeze({
    id: manifest.id,
    version: manifest.version,
    digest: `sha256:${createHash("sha256").update(JSON.stringify(manifest)).digest("hex")}`,
  });
}

type EvidenceBridge = (request: Omit<EvidenceRequest, "signal">) => Promise<unknown>;
type RuleCheckBridge = (request: RuleCheckRequest) => Promise<unknown>;

export type CapabilityRoutingInput = {
  mode: CapabilityMode;
  posture?: PreparedPosture | "chat";
  getEvidence?: EvidenceBridge;
  getRuleCheck?: RuleCheckBridge;
  runIsolatedCommand?: RunGovernedPiIsolatedCommand;
};

export type CapabilityRouting = {
  prepared: boolean;
  hostEvidence: boolean;
  hostRules: boolean;
  isolatedExecution: boolean;
  getEvidence?: EvidenceBridge;
  getRuleCheck?: RuleCheckBridge;
  runIsolatedCommand?: RunGovernedPiIsolatedCommand;
};

export function routeCapabilities(options: CapabilityRoutingInput): CapabilityRouting {
  const prepared =
    options.mode === "inspection" &&
    (options.posture === "inspect" || options.posture === "verify" || options.posture === "review");
  const hostEvidence = prepared && options.getEvidence !== undefined;
  const hostRules = prepared && options.getRuleCheck !== undefined;
  const isolatedExecution =
    prepared && options.posture === "review" && options.runIsolatedCommand !== undefined;

  return {
    prepared,
    hostEvidence,
    hostRules,
    isolatedExecution,
    getEvidence: hostEvidence ? options.getEvidence : undefined,
    getRuleCheck: hostRules ? options.getRuleCheck : undefined,
    runIsolatedCommand: isolatedExecution ? options.runIsolatedCommand : undefined,
  };
}

import type {
  EvidenceRequest,
  RuleCheckRequest,
  RunGovernedPiIsolatedCommand,
} from "./pi-turn-adapter.ts";

export type PreparedPosture = "inspect" | "verify" | "review";
export type CapabilityMode = "inspection" | "chat" | undefined;

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

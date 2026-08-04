import { spawn } from "node:child_process";
import { mkdir, rename, rm, writeFile } from "node:fs/promises";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export type CapabilityPosture = "inspect" | "verify" | "review";

export type CapabilityRecord = {
  [key: string]: unknown;
  posture?: string;
  status?: string;
  events?: unknown;
  evidenceIds?: unknown;
  deterministicChecks?: unknown;
};

export type CapabilityCase = {
  id: string;
  label: string;
  posture: CapabilityPosture;
  question: string;
  expectedStatus: "completed" | "cancelled";
  requiresVm: boolean;
  requiredTools: readonly string[];
  forbiddenTools: readonly string[];
  requiresEvidence: boolean;
  requiresDeterministicCheck: boolean;
  requiresAdmittedProvenance: boolean;
};

export type CapabilityDiagnostic = {
  code: string;
  message: string;
};

export type CapabilityEvaluation = {
  caseId: string;
  passed: boolean;
  vmRequired: boolean;
  status: string | undefined;
  toolNames: string[];
  diagnostics: CapabilityDiagnostic[];
};

export type CapabilityCaseResult = {
  caseId: string;
  record: CapabilityRecord | null;
  stdout: string;
  stderr: string;
  exitCode: number | null;
  signal: string | null;
  evaluation: CapabilityEvaluation;
};

export type CapabilityReport = {
  schemaVersion: 1;
  generatedAt?: string;
  project?: string;
  provider?: string;
  model?: string;
  cases: readonly CapabilityCase[];
  results: readonly CapabilityCaseResult[];
  summary: { passed: number; failed: number };
};

export const CAPABILITY_CASES: readonly CapabilityCase[] = [
  {
    id: "inspect-evidence",
    label: "Inspect a grounded topology lookup",
    posture: "inspect",
    question: "Which equipment tags are present in the prepared topology?",
    expectedStatus: "completed",
    requiresVm: false,
    requiredTools: ["portlog_evidence"],
    forbiddenTools: ["portlog_rule_check", "portlog_isolated_command"],
    requiresEvidence: true,
    requiresDeterministicCheck: false,
    requiresAdmittedProvenance: false,
  },
  {
    id: "inspect-missing",
    label: "Inspect a missing or unsupported identifier",
    posture: "inspect",
    question: "Is equipment P-101 present in the prepared topology?",
    expectedStatus: "completed",
    requiresVm: false,
    requiredTools: ["portlog_evidence"],
    forbiddenTools: ["portlog_rule_check", "portlog_isolated_command"],
    requiresEvidence: true,
    requiresDeterministicCheck: false,
    requiresAdmittedProvenance: false,
  },
  {
    id: "verify-deterministic",
    label: "Run a deterministic rule check",
    posture: "verify",
    question: "Does the pump discharge path satisfy the bundled deterministic check?",
    expectedStatus: "completed",
    requiresVm: false,
    requiredTools: ["portlog_rule_check"],
    forbiddenTools: ["portlog_isolated_command"],
    requiresEvidence: false,
    requiresDeterministicCheck: true,
    requiresAdmittedProvenance: false,
  },
  {
    id: "review-isolated",
    label: "Review with bounded native analysis",
    posture: "review",
    question:
      "Review the prepared topology and run the approved isolated command if native analysis is required.",
    expectedStatus: "completed",
    requiresVm: true,
    requiredTools: ["portlog_evidence", "portlog_rule_check", "portlog_isolated_command"],
    forbiddenTools: [],
    requiresEvidence: false,
    requiresDeterministicCheck: false,
    requiresAdmittedProvenance: true,
  },
  {
    id: "review-cancelled",
    label: "Cancel an isolated review",
    posture: "review",
    question: "Run the approved isolated review and cancel it during execution.",
    expectedStatus: "cancelled",
    requiresVm: true,
    requiredTools: ["portlog_isolated_command"],
    forbiddenTools: [],
    requiresEvidence: false,
    requiresDeterministicCheck: false,
    requiresAdmittedProvenance: false,
  },
];

const MAX_CAPTURED_OUTPUT = 128_000;
const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const REVIEW_COMMAND = join(dirname(fileURLToPath(import.meta.url)), "portlog-review.ts");

export function evaluateCapabilityCase(
  capability: CapabilityCase,
  record: CapabilityRecord | null | undefined,
): CapabilityEvaluation {
  const diagnostics: CapabilityDiagnostic[] = [];
  const toolNames = readToolNames(record);
  const status = typeof record?.status === "string" ? record.status : undefined;

  if (!record) {
    diagnostics.push({
      code: "missing_record",
      message: "The terminal command did not produce a PortLog record.",
    });
  }
  if (record?.posture !== capability.posture) {
    diagnostics.push({
      code: "posture_mismatch",
      message: `Expected posture ${capability.posture}, got ${String(record?.posture ?? "missing")}.`,
    });
  }
  if (status !== capability.expectedStatus) {
    diagnostics.push({
      code: "status_mismatch",
      message: `Expected status ${capability.expectedStatus}, got ${String(status ?? "missing")}.`,
    });
  }

  for (const requiredTool of capability.requiredTools) {
    if (!toolNames.includes(requiredTool)) {
      diagnostics.push({
        code: "missing_tool",
        message: `Expected tool ${requiredTool} in the PortLog event path.`,
      });
    }
  }
  for (const forbiddenTool of capability.forbiddenTools) {
    if (toolNames.includes(forbiddenTool)) {
      diagnostics.push({
        code: "forbidden_tool",
        message: `Tool ${forbiddenTool} is not allowed for this capability case.`,
      });
    }
  }
  if (capability.requiresEvidence && !hasEvidence(record)) {
    diagnostics.push({
      code: "missing_evidence",
      message: "The completed record has no persisted evidence identifier.",
    });
  }
  if (capability.requiresDeterministicCheck && !hasCompletedDeterministicCheck(record)) {
    diagnostics.push({
      code: "missing_deterministic_check",
      message: "The record has no completed deterministic check result.",
    });
  }
  if (capability.requiresAdmittedProvenance && !hasAdmittedProvenance(record)) {
    diagnostics.push({
      code: "missing_admitted_provenance",
      message: "The isolated review has no admitted host-authored provenance.",
    });
  }

  return {
    caseId: capability.id,
    passed: diagnostics.length === 0,
    vmRequired: capability.requiresVm,
    status,
    toolNames,
    diagnostics,
  };
}

export function extractPortLogRecord(stdout: string): CapabilityRecord {
  const marker = "FINAL PORTLOG RECORD";
  const markerIndex = stdout.lastIndexOf(marker);
  if (markerIndex === -1) throw new Error("Terminal output did not contain FINAL PORTLOG RECORD.");
  const jsonText = stdout.slice(markerIndex + marker.length).trim();
  const parsed: unknown = JSON.parse(jsonText);
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed))
    throw new Error("FINAL PORTLOG RECORD was not a JSON object.");
  return parsed as CapabilityRecord;
}

export async function writeCapabilityReport(
  outputPath: string,
  report: CapabilityReport,
): Promise<void> {
  const absolutePath = resolve(outputPath);
  const temporaryPath = join(
    dirname(absolutePath),
    `.${basename(absolutePath)}.${process.pid}.tmp`,
  );
  await mkdir(dirname(absolutePath), { recursive: true });
  try {
    await writeFile(temporaryPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
    await rename(temporaryPath, absolutePath);
  } finally {
    await rm(temporaryPath, { force: true });
  }
}

type ProcessResult = {
  exitCode: number | null;
  signal: NodeJS.Signals | null;
  stdout: string;
  stderr: string;
};

type ExecuteReview = (args: string[], environment: NodeJS.ProcessEnv) => Promise<ProcessResult>;

export type RunCapabilityMatrixOptions = {
  project: string;
  provider: string;
  model: string;
  baseUrl?: string;
  sidecarEndpoint?: string;
  outputPath?: string;
  caseIds?: readonly string[];
  environment?: NodeJS.ProcessEnv;
  executeReview?: ExecuteReview;
};

export async function runCapabilityMatrix(
  options: RunCapabilityMatrixOptions,
): Promise<CapabilityReport> {
  const selectedCases = selectCases(options.caseIds);
  const executeReview =
    options.executeReview ?? ((args, environment) => runReviewCommand(args, environment));
  const results: CapabilityCaseResult[] = [];

  for (const capability of selectedCases) {
    const args = [
      "--project",
      options.project,
      "--provider",
      options.provider,
      "--model",
      options.model,
      "--posture",
      capability.posture,
      "--question",
      capability.question,
    ];
    if (options.baseUrl) args.push("--base-url", options.baseUrl);
    if (options.sidecarEndpoint) args.push("--sidecar-endpoint", options.sidecarEndpoint);

    const processResult = await executeReview(args, {
      ...process.env,
      ...options.environment,
    });
    let record: CapabilityRecord | undefined;
    try {
      record = extractPortLogRecord(processResult.stdout);
    } catch {
      record = undefined;
    }
    results.push({
      caseId: capability.id,
      record: record ?? null,
      stdout: processResult.stdout,
      stderr: processResult.stderr,
      exitCode: processResult.exitCode,
      signal: processResult.signal,
      evaluation: evaluateCapabilityCase(capability, record),
    });
  }

  const report: CapabilityReport = {
    schemaVersion: 1,
    generatedAt: new Date().toISOString(),
    project: resolve(options.project),
    provider: options.provider,
    model: options.model,
    cases: selectedCases,
    results,
    summary: {
      passed: results.filter((result) => result.evaluation.passed).length,
      failed: results.filter((result) => !result.evaluation.passed).length,
    },
  };
  await writeCapabilityReport(options.outputPath ?? "portlog-capability-report.json", report);
  return report;
}

function selectCases(caseIds: readonly string[] | undefined): CapabilityCase[] {
  if (!caseIds || caseIds.length === 0)
    return [...CAPABILITY_CASES].filter((item) => item.id !== "review-cancelled");
  const selected: CapabilityCase[] = [];
  for (const caseId of caseIds) {
    const capability = CAPABILITY_CASES.find((item) => item.id === caseId);
    if (!capability) throw new Error(`Unknown capability case ${caseId}.`);
    selected.push(capability);
  }
  return selected;
}

async function runReviewCommand(
  args: string[],
  environment: NodeJS.ProcessEnv,
): Promise<ProcessResult> {
  const child = spawn(process.execPath, ["--experimental-strip-types", REVIEW_COMMAND, ...args], {
    cwd: REPO_ROOT,
    env: environment,
    stdio: ["ignore", "pipe", "pipe"],
  });
  let stdout = "";
  let stderr = "";
  child.stdout.on("data", (chunk) => {
    stdout = appendTail(stdout, String(chunk));
  });
  child.stderr.on("data", (chunk) => {
    stderr = appendTail(stderr, String(chunk));
  });
  const [exitCode, signal] = await new Promise<[number | null, NodeJS.Signals | null]>(
    (resolveExit, rejectExit) => {
      child.once("error", rejectExit);
      child.once("exit", (code, childSignal) => resolveExit([code, childSignal]));
    },
  );
  return { exitCode, signal, stdout, stderr };
}

function appendTail(existing: string, chunk: string): string {
  const combined = existing + chunk;
  return combined.length <= MAX_CAPTURED_OUTPUT
    ? combined
    : combined.slice(combined.length - MAX_CAPTURED_OUTPUT);
}

function readToolNames(record: CapabilityRecord | null | undefined): string[] {
  const names: string[] = [];
  if (!Array.isArray(record?.events)) return names;
  for (const event of record.events) {
    if (!event || typeof event !== "object") continue;
    const tool = (event as Record<string, unknown>).tool;
    if (typeof tool === "string" && !names.includes(tool)) names.push(tool);
  }
  return names;
}

function hasEvidence(record: CapabilityRecord | null | undefined): boolean {
  return (
    Array.isArray(record?.evidenceIds) &&
    record.evidenceIds.some((value) => typeof value === "string")
  );
}

function hasCompletedDeterministicCheck(record: CapabilityRecord | null | undefined): boolean {
  return (
    Array.isArray(record?.deterministicChecks) &&
    record.deterministicChecks.some(
      (value) =>
        value !== null &&
        typeof value === "object" &&
        (value as Record<string, unknown>).run_status === "completed",
    )
  );
}

function hasAdmittedProvenance(record: CapabilityRecord | null | undefined): boolean {
  return containsAdmittedProvenance(record);
}

function containsAdmittedProvenance(value: unknown): boolean {
  if (Array.isArray(value)) return value.some((item) => containsAdmittedProvenance(item));
  if (value === null || typeof value !== "object") return false;
  const object = value as Record<string, unknown>;
  const provenance = object.provenance;
  if (
    provenance !== null &&
    typeof provenance === "object" &&
    (provenance as Record<string, unknown>).outcome === "admitted" &&
    (provenance as Record<string, unknown>).backend !== undefined &&
    (provenance as Record<string, unknown>).policy !== undefined
  )
    return true;
  return Object.values(object).some((item) => containsAdmittedProvenance(item));
}

function parseCli(argv: string[]): RunCapabilityMatrixOptions & { help: boolean } {
  const values: Record<string, string | undefined> = {};
  const caseIds: string[] = [];
  let help = false;
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === "--help" || argument === "-h") {
      help = true;
      continue;
    }
    const [name, inlineValue] = argument.split("=", 2);
    const value = inlineValue ?? argv[++index];
    if (name === "--case") {
      if (!value) throw new Error("--case requires a value");
      caseIds.push(value);
    } else if (name.startsWith("--")) {
      if (!value) throw new Error(`${name} requires a value`);
      values[name.slice(2)] = value;
    } else {
      throw new Error(`Unknown option ${name}`);
    }
  }
  return {
    help,
    project: values.project ?? "",
    provider: values.provider ?? "",
    model: values.model ?? "",
    baseUrl: values["base-url"],
    sidecarEndpoint: values["sidecar-endpoint"],
    outputPath: values.output ?? "portlog-capability-report.json",
    caseIds,
  };
}

const USAGE = `Usage:
  node --experimental-strip-types desktop/portlog-capability-eval.ts \\
    --project PATH --provider PROVIDER --model MODEL [options]

Options:
  --base-url URL             Provider base URL override.
  --sidecar-endpoint URL     Existing trusted PortLog sidecar.
  --case ID                  Run one matrix case; may be repeated.
  --output PATH              Report path (default: portlog-capability-report.json).
`;

async function main(): Promise<void> {
  const options = parseCli(process.argv.slice(2));
  if (options.help) {
    console.log(USAGE);
    return;
  }
  if (!options.project || !options.provider || !options.model)
    throw new Error(`--project, --provider, and --model are required.\n\n${USAGE}`);
  const report = await runCapabilityMatrix(options);
  console.log(
    `Capability report: ${report.summary.passed} passed, ${report.summary.failed} failed; ${options.outputPath}`,
  );
  if (report.summary.failed > 0) process.exitCode = 1;
}

if (process.argv[1] && resolve(process.argv[1]) === resolve(fileURLToPath(import.meta.url))) {
  void main().catch((error) => {
    console.error(`ERROR: ${error instanceof Error ? error.message : String(error)}`);
    process.exitCode = 1;
  });
}

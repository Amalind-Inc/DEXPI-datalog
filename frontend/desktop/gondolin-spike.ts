import { createHash, randomUUID } from "node:crypto";

import {
  GONDOLIN_CANCELLATION_PROFILE,
  GONDOLIN_CONFINEMENT_PROFILE,
  GONDOLIN_REVIEW_CANDIDATE_PROFILE,
  createGondolinQemuExecutor,
} from "./gondolin-qemu.ts";
import type {
  ApprovedCommandProfile,
  ImmutableInputBundle,
  IsolatedCommandLimits,
  IsolatedCommandRequest,
  IsolatedCommandResult,
} from "./isolated-command.ts";

type Scenario = "candidate" | "confinement" | "cancel" | "init-failure" | "rejected";

type Options = {
  scenario: Scenario;
  qemuPath: string;
  help: boolean;
};

const DEFAULT_QEMU_PATH = "/opt/homebrew/bin/qemu-system-aarch64";
const INPUT_TEXT = '{"asset":"C01 DEXPI review spike","claim":"P4711 bounded guest input"}\n';
const MAX_DISPLAYED_JSON_CHARS = 4_000;
const USAGE = `Disposable Gondolin approved-profile spike

Usage:
  npm run prototype:gondolin -- --scenario candidate
  npm run prototype:gondolin -- --scenario confinement
  npm run prototype:gondolin -- --scenario cancel
  npm run prototype:gondolin -- --scenario init-failure
  npm run prototype:gondolin -- --scenario rejected

Scenarios:
  candidate       Stage immutable input and admit one bounded result.json candidate.
  confinement     Probe deny-all networking and ambient credential/config access.
  cancel          Run the approved hold profile; press Ctrl-C to cancel it.
  init-failure    Use a missing QEMU path; no host fallback is attempted.
  rejected        Request an unapproved profile; no guest is started.

Optional environment:
  PORTLOG_QEMU_PATH    Absolute QEMU path; default: ${DEFAULT_QEMU_PATH}
`;

await main(process.argv.slice(2));

async function main(argv: string[]): Promise<void> {
  const options = parseArgs(argv);
  if (options.help) {
    console.log(USAGE);
    return;
  }

  const controller = new AbortController();
  const abort = () => controller.abort();
  process.once("SIGINT", abort);
  process.once("SIGTERM", abort);

  try {
    const request = createRequest(options.scenario, controller.signal);
    const qemuPath =
      options.scenario === "init-failure" ? "/definitely/missing/portlog-qemu" : options.qemuPath;
    console.log("DISPOSABLE GONDOLIN SPIKE");
    console.log(`SCENARIO: ${options.scenario}`);
    console.log(`APPROVED PROFILE: ${request.commandProfile.id}@${request.commandProfile.version}`);
    console.log(`HOST DISPATCH: absolute QEMU path ${qemuPath}`);
    console.log(
      `INPUT: ${request.inputBundle.files.length} immutable file staged at /review/input/review.json`,
    );
    console.log(
      "GUEST POLICY: deny-all networking; empty guest environment; read-only input; memory rootfs",
    );
    console.log(
      "HOST FALLBACK: none; initialization or execution failure is returned without host execution",
    );

    const executor = createGondolinQemuExecutor({ qemuPath });
    const result = await executor.runIsolatedCommand(request);
    printResult(result);
    if (result.outcome !== "admitted" && result.outcome !== "cancelled") process.exitCode = 1;
  } catch (error) {
    if (controller.signal.aborted) {
      console.log("CANCELLED: Gondolin spike stopped before a result was admitted.");
      process.exitCode = 130;
    } else {
      process.exitCode = 1;
      console.error(`ERROR: ${error instanceof Error ? error.message : String(error)}`);
    }
  } finally {
    process.removeListener("SIGINT", abort);
    process.removeListener("SIGTERM", abort);
  }
}

function parseArgs(argv: string[]): Options {
  const options: Options = {
    scenario: "candidate",
    qemuPath: process.env.PORTLOG_QEMU_PATH ?? DEFAULT_QEMU_PATH,
    help: false,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === "--help" || argument === "-h") {
      options.help = true;
      continue;
    }
    const [name, inlineValue] = splitOption(argument);
    const value = inlineValue ?? argv[++index];
    if (!value) throw new Error(`${name} requires a value.\n\n${USAGE}`);
    if (name === "--scenario") options.scenario = readScenario(value);
    else if (name === "--qemu-path") options.qemuPath = value;
    else throw new Error(`Unknown option ${name}.\n\n${USAGE}`);
  }
  return options;
}

function splitOption(argument: string): [string, string | undefined] {
  const equals = argument.indexOf("=");
  return equals === -1
    ? [argument, undefined]
    : [argument.slice(0, equals), argument.slice(equals + 1)];
}

function readScenario(value: string): Scenario {
  if (
    value === "candidate" ||
    value === "confinement" ||
    value === "cancel" ||
    value === "init-failure" ||
    value === "rejected"
  )
    return value;
  throw new Error(
    `Unknown scenario ${value}; choose candidate, confinement, cancel, init-failure, or rejected.`,
  );
}

function createRequest(scenario: Scenario, signal: AbortSignal): IsolatedCommandRequest {
  const inputBundle = createImmutableInputBundle();
  const commandProfile = profileForScenario(scenario);
  const limits: IsolatedCommandLimits = {
    maxDurationMs: scenario === "cancel" ? 15_000 : 60_000,
    maxMemoryBytes: 2 * 1024 * 1024 * 1024,
    maxCpuSeconds: 30,
    maxScratchBytes: 64 * 1024,
    maxOutputCount: 1,
    maxOutputBytes: 1_024,
    maxInputFiles: 4,
    maxInputBytes: 64 * 1024,
  };
  return {
    runId: `gondolin-spike-${randomUUID()}`,
    inputBundle,
    commandProfile,
    limits,
    signal,
  };
}

function createImmutableInputBundle(): ImmutableInputBundle {
  const bytes = new TextEncoder().encode(INPUT_TEXT);
  const digest = `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
  return {
    bundleId: "gondolin-spike-c01-input",
    digest,
    files: [
      {
        relativePath: "review.json",
        bytes,
        digest,
      },
    ],
  };
}

function profileForScenario(scenario: Scenario): ApprovedCommandProfile {
  if (scenario === "candidate" || scenario === "init-failure")
    return GONDOLIN_REVIEW_CANDIDATE_PROFILE;
  if (scenario === "confinement") return GONDOLIN_CONFINEMENT_PROFILE;
  if (scenario === "cancel") return GONDOLIN_CANCELLATION_PROFILE;
  return { id: "not-approved", version: "1" };
}

function printResult(result: IsolatedCommandResult): void {
  console.log("RESULT");
  console.log(`OUTCOME: ${result.outcome}`);
  console.log(
    `ORIGIN: ${result.outcome === "admitted" ? "guest command; host-authored provenance" : "no guest artifact admitted"}`,
  );
  console.log(`DIAGNOSTIC: ${result.diagnostic}`);
  if (result.exitCode !== undefined) console.log(`GUEST EXIT CODE: ${result.exitCode}`);
  if (result.outcome === "admitted") {
    if (result.candidate) console.log(`BOUNDED GUEST OUTPUT: ${JSON.stringify(result.candidate)}`);
    if (result.provenance.artifact)
      console.log(`GUEST ARTIFACT: ${JSON.stringify(result.provenance.artifact)}`);
  }
  console.log(`PROVENANCE: ${limit(JSON.stringify(result.provenance))}`);
  console.log("NO DURABLE GUEST WORKSPACE: rootfs and staged mounts were disposable.");
  console.log("NO HOST FALLBACK: this result came only from the approved isolated-command path.");
}

function limit(value: string): string {
  return value.length <= MAX_DISPLAYED_JSON_CHARS
    ? value
    : `${value.slice(0, MAX_DISPLAYED_JSON_CHARS)}…`;
}

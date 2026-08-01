import { spawn, execFile as execFileCb } from "node:child_process";
import net from "node:net";
import http from "node:http";
import { existsSync, openSync } from "node:fs";
import { mkdir, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";
import playwright from "playwright";

const { _electron } = playwright;
const execFile = promisify(execFileCb);
const repo = path.resolve("..");
const frontend = path.join(repo, "frontend");
const root = path.join(repo, ".tmp", "electron-native-acceptance-run");
const logs = path.join(root, "logs");
const userData = path.join(root, "userData");
const packagedApp = process.env.PORTLOG_RELEASE_APP
  ? path.resolve(process.env.PORTLOG_RELEASE_APP)
  : "";
const packagedExecutable = packagedApp
  ? path.join(packagedApp, "Contents", "MacOS", "PortLog")
  : "";
const cleanEnv = {
  PATH: "/usr/bin:/bin:/usr/sbin:/sbin",
  HOME: process.env.HOME ?? "/tmp/portlog-clean-home",
  TMPDIR: process.env.TMPDIR ?? "/tmp",
  LANG: "en_US.UTF-8",
};
const timings = {};
const fixture = path.join(
  repo,
  "TrainingTestCases/dexpi 1.3/example pids/C01 DEXPI Reference P&ID/C01V04-VER.EX01.xml",
);
let modelServerUrl = "";
const modelServer = http.createServer(async (request, response) => {
  let body = "";
  for await (const chunk of request) body += chunk;
  const parsed = JSON.parse(body || "{}");
  const text = JSON.stringify(parsed.messages ?? []);
  if (/cancel this inspection/i.test(text)) return;
  response.writeHead(200, { "content-type": "text/event-stream" });
  const hasToolResult = (parsed.messages ?? []).some((message) => message.role === "tool");
  const isGeneral = !Array.isArray(parsed.tools) || parsed.tools.length === 0;
  const isVerify = /check valve/i.test(text);
  const delta = isGeneral
    ? {
        role: "assistant",
        content: "Hello from desktop chat without a prepared P&ID.",
      }
    : hasToolResult
      ? {
          role: "assistant",
          content: isVerify
            ? "The deterministic check completed; the PortLog-owned outcome is shown separately."
            : "The prepared topology contains bounded evidence around P4711. See the selected evidence.",
        }
      : {
          role: "assistant",
          tool_calls: [
            {
              id: isVerify ? "call-native-rule-1" : "call-native-1",
              type: "function",
              function: isVerify
                ? {
                    name: "portlog_rule_check",
                    arguments: JSON.stringify({
                      checkId: "pump_discharge_check_valve",
                      scopeEntityId: "CentrifugalPump-1",
                    }),
                  }
                : {
                    name: "portlog_evidence",
                    arguments: JSON.stringify({
                      artifactId: "topology",
                      claim: "equipment and connections around P4711",
                    }),
                  },
            },
          ],
        };
  response.write(
    `data: ${JSON.stringify({ id: "native", object: "chat.completion.chunk", choices: [{ index: 0, delta, finish_reason: isGeneral || hasToolResult ? "stop" : "tool_calls" }] })}\n\n`,
  );
  response.end("data: [DONE]\n\n");
});

async function assertPortFree(port) {
  try {
    const { stdout } = await execFile("lsof", ["-ti", `tcp:${port}`]);
    const pids = stdout.trim().split("\n").filter(Boolean);
    if (pids.length > 0)
      throw new Error(
        `Port ${port} is already in use by PID(s) ${pids.join(", ")}; stop that process or choose a free development port before running test:desktop-native.`,
      );
  } catch (error) {
    if (error instanceof Error && error.message.includes("already in use")) throw error;
  }
}

async function waitFor(url, attempts = 100) {
  for (let i = 0; i < attempts; i += 1) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Timed out waiting for ${url}`);
}

async function waitForUnavailable(url, attempts = 100) {
  for (let i = 0; i < attempts; i += 1) {
    try {
      await fetch(url);
    } catch {
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Timed out waiting for ${url} to stop responding`);
}

async function waitForExit(child, name) {
  if (child.exitCode !== null) return;
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`${name} did not exit`)), 10_000);
    child.once("exit", () => {
      clearTimeout(timer);
      resolve();
    });
  });
}

async function launchElectron(extraEnv = {}) {
  const env = packagedApp
    ? {
        ...cleanEnv,
        OPENROUTER_API_KEY: "sk-or-test-visible-status",
        PORTLOG_OPENROUTER_BASE_URL: modelServerUrl,
        PORTLOG_DESKTOP_USER_DATA_DIR: userData,
        PORTLOG_QUIT_ON_WINDOW_ALL_CLOSED: "1",
        ...extraEnv,
      }
    : {
        ...process.env,
        OPENROUTER_API_KEY: "sk-or-test-visible-status",
        PORTLOG_OPENROUTER_BASE_URL: modelServerUrl,
        ...extraEnv,
        PORTLOG_DESKTOP_UI_URL: "http://127.0.0.1:3000",
        PORTLOG_DESKTOP_USER_DATA_DIR: userData,
        PORTLOG_QUIT_ON_WINDOW_ALL_CLOSED: "1",
      };
  const app = await _electron.launch(
    packagedApp
      ? { executablePath: packagedExecutable, env }
      : { cwd: frontend, args: ["desktop/electron-main.cjs"], env },
  );
  const window = await app.firstWindow();
  await window.getByRole("region", { name: "Chat" }).waitFor({ state: "visible", timeout: 30_000 });
  return { app, window };
}

async function closeElectron(instance) {
  await instance.window.close();
  await instance.app.close();
}

await Promise.all([...(packagedApp ? [] : [assertPortFree(3000)]), assertPortFree(8000)]);
modelServer.listen(0, "127.0.0.1");
await new Promise((resolve) => modelServer.once("listening", resolve));
const modelAddress = modelServer.address();
if (!modelAddress || typeof modelAddress === "string")
  throw new Error("Controlled model server did not bind");
modelServerUrl = `http://127.0.0.1:${modelAddress.port}/v1`;
await rm(root, { recursive: true, force: true });
await mkdir(logs, { recursive: true });
let next = null;
if (!packagedApp) {
  const nextLog = openSync(path.join(logs, "next.log"), "a");
  next = spawn("npm", ["run", "dev", "--", "--hostname", "127.0.0.1", "--port", "3000"], {
    cwd: frontend,
    env: { ...process.env, HARBORFIELD_DISABLE_BYOK: "1" },
    stdio: ["ignore", nextLog, nextLog],
  });
  await waitFor("http://127.0.0.1:3000/assistant");
}
try {
  const launchStarted = Date.now();
  const first = await launchElectron();
  timings.first_launch_ms = Date.now() - launchStarted;
  await first.window
    .getByTestId("desktop-openrouter-status")
    .getByText("OpenRouter / deepseek/deepseek-v4-flash / Configured")
    .waitFor({ state: "visible", timeout: 30_000 });
  const generalMessage = first.window.getByLabel("Message input");
  await generalMessage.fill("Say hello without an uploaded P&ID.");
  await first.window.getByRole("button", { name: "Send message" }).click();
  await first.window
    .getByText("Hello from desktop chat without a prepared P&ID.")
    .waitFor({ state: "visible", timeout: 30_000 });
  const uploadChooser = first.window.waitForEvent("filechooser");
  await first.window.getByRole("button", { name: "Add Attachment" }).click();
  await (await uploadChooser).setFiles(fixture);
  await first.window
    .getByText("Process document ready")
    .waitFor({ state: "visible", timeout: 30_000 });
  await first.window
    .getByLabel("Message input")
    .fill("What equipment and connections are around P4711?");
  await first.window.getByRole("button", { name: "Send message" }).click();
  await first.window
    .getByText(
      "The prepared topology contains bounded evidence around P4711. See the selected evidence.",
    )
    .waitFor({ state: "visible", timeout: 30_000 });
  const preparationStarted = Date.now();
  await first.app.evaluate(({ dialog }, fixturePath) => {
    dialog.showOpenDialog = async () => ({ canceled: false, filePaths: [fixturePath] });
  }, fixture);
  await first.window.getByRole("button", { name: /^Import DEXPI/ }).click();
  await first.window
    .getByRole("complementary", { name: "Process document graph panel" })
    .getByText("C01V04-VER.EX01.xml")
    .waitFor({ state: "visible", timeout: 30_000 });
  timings.preparation_ms = Date.now() - preparationStarted;
  const manifest = path.join(userData, "current-project", "portlog-project.json");
  if (!existsSync(manifest)) throw new Error(`Manifest was not persisted: ${manifest}`);
  const question = first.window.getByLabel("Ask about this prepared P&ID");
  await question.fill("What equipment and connections are around P4711?");
  const inspectionStarted = Date.now();
  await first.window.getByRole("button", { name: "Inspect", exact: true }).click();
  const completed = first.window
    .getByTestId("desktop-inspection-turn")
    .filter({ hasText: "completed" });
  await completed.waitFor({ state: "visible", timeout: 30_000 });
  await completed.getByText("tool request · portlog_evidence").click();
  await completed
    .getByText(/equipment and connections around P4711/)
    .first()
    .waitFor({ state: "visible" });
  await completed.getByRole("button", { name: /Select evidence/ }).click();
  timings.inspection_ms = Date.now() - inspectionStarted;

  await first.window.getByLabel("Review posture").selectOption("verify");
  await question.fill("Does pump P4711 have a downstream check valve?");
  const verificationStarted = Date.now();
  await first.window.getByRole("button", { name: "Inspect", exact: true }).click();
  const verified = first.window
    .getByTestId("desktop-inspection-turn")
    .filter({ hasText: "Verify" })
    .filter({ hasText: "completed" });
  await verified.waitFor({ state: "visible", timeout: 30_000 });
  await verified.getByTestId("deterministic-check-result").waitFor({ state: "visible" });
  timings.verification_ms = Date.now() - verificationStarted;

  await first.window.getByLabel("Review posture").selectOption("inspect");
  await question.fill("Cancel this inspection while the model is active");
  const cancellationStarted = Date.now();
  await first.window.getByRole("button", { name: "Inspect", exact: true }).click();
  await first.window.getByRole("button", { name: "Cancel", exact: true }).click();
  await first.window
    .getByTestId("desktop-inspection-turn")
    .filter({ hasText: "cancelled" })
    .waitFor({ state: "visible", timeout: 30_000 });
  timings.cancellation_ms = Date.now() - cancellationStarted;
  await closeElectron(first);
  await waitForUnavailable("http://127.0.0.1:8000/openapi.json");

  const relaunchStarted = Date.now();
  const second = await launchElectron();
  timings.relaunch_ms = Date.now() - relaunchStarted;
  await second.window
    .getByRole("complementary", { name: "Process document graph panel" })
    .getByText("C01V04-VER.EX01.xml")
    .waitFor({ state: "visible", timeout: 30_000 });
  await second.window
    .getByTestId("desktop-inspection-turn")
    .filter({ hasText: "Inspect · completed" })
    .waitFor({ state: "visible", timeout: 30_000 });
  await second.window
    .getByTestId("desktop-inspection-turn")
    .filter({ hasText: "Verify · completed" })
    .waitFor({ state: "visible", timeout: 30_000 });
  await second.window
    .getByTestId("desktop-inspection-turn")
    .filter({ hasText: "cancelled" })
    .waitFor({ state: "visible", timeout: 30_000 });
  await closeElectron(second);

  const missing = await launchElectron({
    PORTLOG_IGNORE_LOCAL_OPENROUTER_ENV: "1",
    OPENROUTER_API_KEY: "",
  });
  await missing.window
    .getByTestId("desktop-openrouter-status")
    .getByText(
      "OpenRouter is not configured. Add OPENROUTER_API_KEY to the local .env file and relaunch PortLog.",
    )
    .waitFor({ state: "visible", timeout: 30_000 });
  await missing.window
    .getByTestId("desktop-claude-auth-status")
    .getByText("Claude: logged_out")
    .waitFor({ state: "visible", timeout: 30_000 });
  await missing.window
    .getByRole("button", { name: "Log in with Claude" })
    .waitFor({ state: "visible" });
  await missing.window
    .getByText(/does not include PortLog usage/)
    .waitFor({ state: "visible", timeout: 30_000 });
  await closeElectron(missing);

  const crashed = await launchElectron();
  const crashedQuestion = crashed.window.getByLabel("Ask about this prepared P&ID");
  await crashedQuestion.fill("Cancel this inspection while the model is active");
  await crashed.window.getByRole("button", { name: "Inspect", exact: true }).click();
  await crashed.window
    .getByRole("button", { name: "Cancel", exact: true })
    .waitFor({ state: "visible", timeout: 30_000 });
  const crashedProcess = crashed.app.process();
  const sidecarPids = (await execFile("lsof", ["-ti", "tcp:8000"])).stdout
    .trim()
    .split("\n")
    .filter(Boolean)
    .map((pid) => Number(pid));
  if (!sidecarPids.length)
    throw new Error("Packaged sidecar did not expose a PID for crash cleanup");
  for (const pid of sidecarPids) process.kill(pid, "SIGKILL");
  await waitForExit(crashedProcess, "Electron after sidecar crash");
  await waitForUnavailable("http://127.0.0.1:8000/openapi.json");

  const forced = await launchElectron();
  const forcedProcess = forced.app.process();
  forcedProcess.kill("SIGKILL");
  await waitForExit(forcedProcess, "forced Electron termination");
  await waitForUnavailable("http://127.0.0.1:8000/openapi.json");

  const blocker = net.createServer();
  await new Promise((resolve, reject) => {
    blocker.once("error", reject);
    blocker.listen(8000, "127.0.0.1", resolve);
  });
  let failedLaunchRejected = false;
  try {
    const failed = await launchElectron();
    await closeElectron(failed);
  } catch {
    failedLaunchRejected = true;
  } finally {
    await new Promise((resolve) => blocker.close(resolve));
  }
  if (!failedLaunchRejected)
    throw new Error("Packaged launch unexpectedly attached to an occupied sidecar port");
  await waitForUnavailable("http://127.0.0.1:8000/openapi.json");

  const result = {
    ok: true,
    app: packagedApp || "development",
    clean_environment: Boolean(packagedApp),
    manifest,
    cleanup: {
      normal_quit: true,
      inspection_cancel: true,
      sidecar_crash: true,
      forced_termination: true,
      failed_launch: true,
    },
    timings,
  };
  if (process.env.PORTLOG_RELEASE_RESULTS)
    await writeFile(process.env.PORTLOG_RELEASE_RESULTS, `${JSON.stringify(result, null, 2)}\n`);
  console.log(JSON.stringify(result));
} finally {
  if (next) {
    if (next.exitCode === null) next.kill("SIGTERM");
    await waitForExit(next, "Next dev server").catch(() => next.kill("SIGKILL"));
  }
  modelServer.closeAllConnections();
  await new Promise((resolve) => modelServer.close(resolve));
}

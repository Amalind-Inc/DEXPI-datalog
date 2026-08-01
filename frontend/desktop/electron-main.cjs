const fs = require("node:fs/promises");
const path = require("node:path");
const { spawn } = require("node:child_process");
const net = require("node:net");
const { app, BrowserWindow, dialog, ipcMain, shell } = require("electron");
const {
  migrateLegacyProject,
  persistLocalProject,
  loadLocalProject,
} = require("./local-project-manifest.cjs");
const { resolveReviewSidecarPaths } = require("./electron-sidecar-paths.cjs");
const {
  resolveOpenRouterEnv,
  redactedOpenRouterState,
} = require("./electron-openrouter-config.cjs");
const {
  checkOpenRouterConnection: checkResolvedOpenRouterConnection,
} = require("./electron-openrouter-check.cjs");
const { createClaudeAuthController } = require("./claude-auth-controller.cjs");
const { createMacOSClaudeKeychain } = require("./claude-keychain.cjs");
const { createCodexAuthController } = require("./codex-auth-controller.cjs");
const { createMacOSCodexKeychain } = require("./codex-keychain.cjs");
const { createDesktopChatProviderStore } = require("./desktop-chat-provider.cjs");

app.setName("PortLog");
let desktopUiUrl = process.env.PORTLOG_DESKTOP_UI_URL;
if (process.env.PORTLOG_DESKTOP_USER_DATA_DIR)
  app.setPath("userData", process.env.PORTLOG_DESKTOP_USER_DATA_DIR);
const sidecarEndpoint = "http://127.0.0.1:8000";
let sidecar;
let uiServer;
let openRouterEnv;
let claudeAuth;
let codexAuth;
const activeInspections = new Map();

async function waitForSidecar() {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (sidecar?.exitCode !== null)
      throw new Error(`PortLog sidecar exited before readiness: ${sidecar?.exitCode}`);
    try {
      if ((await fetch(`${sidecarEndpoint}/openapi.json`)).ok) return;
    } catch {
      /* starting */
    }
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error("PortLog local review sidecar did not become ready within 5 seconds");
}

async function availableLocalPort() {
  const listener = net.createServer();
  await new Promise((resolve, reject) => {
    listener.once("error", reject);
    listener.listen(0, "127.0.0.1", resolve);
  });
  const address = listener.address();
  await new Promise((resolve) => listener.close(resolve));
  if (!address || typeof address === "string")
    throw new Error("Could not allocate a local UI port");
  return address.port;
}

async function startPackagedUi() {
  if (!app.isPackaged) return;
  const port = await availableLocalPort();
  desktopUiUrl = "http://127.0.0.1:" + port;
  const uiRoot = path.join(process.resourcesPath, "ui");
  uiServer = spawn(process.execPath, [path.join(uiRoot, "server.js")], {
    cwd: uiRoot,
    env: {
      ...process.env,
      ELECTRON_RUN_AS_NODE: "1",
      HOSTNAME: "127.0.0.1",
      PORT: String(port),
      HARBORFIELD_REVIEW_API_URL: sidecarEndpoint,
      NODE_PATH: path.join(uiRoot, "runtime"),
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  uiServer.stderr.on("data", (chunk) => console.error(String(chunk).slice(0, 4000)));
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (uiServer.exitCode !== null)
      throw new Error("Packaged PortLog UI exited before readiness: " + uiServer.exitCode);
    try {
      if ((await fetch(desktopUiUrl + "/assistant")).ok) return;
    } catch {
      /* starting */
    }
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error("Packaged PortLog UI did not become ready within 5 seconds");
}

function childHasExited(child) {
  if (!child || child.exitCode !== null || child.signalCode !== null) return true;
  if (child.pid === null || child.pid === undefined) return true;
  try {
    process.kill(child.pid, 0);
    return false;
  } catch {
    return true;
  }
}

async function terminateChild(child) {
  if (childHasExited(child)) return;
  const exit = new Promise((resolve) => child.once("exit", resolve));
  child.stdin?.end();
  child.kill("SIGTERM");
  const terminated = await Promise.race([
    exit.then(() => true),
    new Promise((resolve) => setTimeout(() => resolve(false), 2_000)),
  ]);
  if (terminated || childHasExited(child)) return;
  child.kill("SIGKILL");
  await Promise.race([exit, new Promise((resolve) => setTimeout(resolve, 2_000))]);
}

async function stopPackagedUi() {
  await terminateChild(uiServer);
}

function repoRootForLocalRuntime() {
  return resolveReviewSidecarPaths({
    isPackaged: app.isPackaged,
    resourcesPath: process.resourcesPath,
    desktopDir: __dirname,
  }).cwd;
}
function resolveCurrentOpenRouterEnv() {
  return resolveOpenRouterEnv({
    appIsPackaged: app.isPackaged,
    repoRoot: repoRootForLocalRuntime(),
    env: process.env,
  });
}

function openRouterStatus() {
  openRouterEnv = resolveCurrentOpenRouterEnv();
  return redactedOpenRouterState(openRouterEnv);
}

async function checkOpenRouterConnection() {
  openRouterEnv = resolveCurrentOpenRouterEnv();
  return checkResolvedOpenRouterConnection({ resolved: openRouterEnv });
}

async function getClaudeAuth() {
  if (claudeAuth) return claudeAuth;
  if (process.platform !== "darwin") throw new Error("Claude login is supported only on macOS.");
  const { anthropicOAuthProvider } = await import("@earendil-works/pi-ai/oauth");
  claudeAuth = createClaudeAuthController({
    oauth: anthropicOAuthProvider,
    keychain: createMacOSClaudeKeychain(),
    openExternal: (url) => shell.openExternal(url),
  });
  return claudeAuth;
}

async function claudeAuthStatus() {
  return (await getClaudeAuth()).status();
}
async function claudeLogin() {
  return (await getClaudeAuth()).login();
}
async function claudeCancelLogin() {
  return (await getClaudeAuth()).cancel();
}
async function claudeLogout() {
  for (const worker of activeInspections.values()) worker.kill("SIGTERM");
  return (await getClaudeAuth()).logout();
}

async function getCodexAuth() {
  if (codexAuth) return codexAuth;
  if (process.platform !== "darwin")
    throw new Error("OpenAI Codex login is supported only on macOS.");
  const { openaiCodexOAuthProvider } = await import("@earendil-works/pi-ai/oauth");
  codexAuth = createCodexAuthController({
    oauth: openaiCodexOAuthProvider,
    keychain: createMacOSCodexKeychain(),
    openExternal: (url) => shell.openExternal(url),
  });
  return codexAuth;
}

async function codexAuthStatus() {
  return (await getCodexAuth()).status();
}
async function codexLogin(method) {
  return (await getCodexAuth()).login(method);
}
async function codexCancelLogin() {
  return (await getCodexAuth()).cancel();
}
async function codexLogout() {
  for (const worker of activeInspections.values()) worker.kill("SIGTERM");
  return (await getCodexAuth()).logout();
}

async function assertSidecarPortFree() {
  await new Promise((resolve, reject) => {
    const probe = net.createConnection({ host: "127.0.0.1", port: 8000 });
    const timer = setTimeout(() => {
      probe.destroy();
      reject(new Error("Timed out probing PortLog sidecar port 8000"));
    }, 1_000);
    probe.once("connect", () => {
      clearTimeout(timer);
      probe.destroy();
      reject(
        new Error(
          "PortLog sidecar port 8000 is already in use; refuse to attach to an unowned process",
        ),
      );
    });
    probe.once("error", (error) => {
      clearTimeout(timer);
      if (error && error.code === "ECONNREFUSED") resolve();
      else reject(error);
    });
  });
}

async function startSidecar() {
  await assertSidecarPortFree();
  const artifactRoot = path.join(app.getPath("userData"), "reviews");
  const { python, cwd } = resolveReviewSidecarPaths({
    isPackaged: app.isPackaged,
    resourcesPath: process.resourcesPath,
    desktopDir: __dirname,
  });
  sidecar = spawn(
    python,
    app.isPackaged
      ? ["--host", "127.0.0.1", "--port", "8000"]
      : ["-m", "uvicorn", "pydexpi_datalog.web.asgi:app", "--host", "127.0.0.1", "--port", "8000"],
    {
      cwd,
      env: {
        ...process.env,
        HARBORFIELD_DEPLOYMENT_PROFILE: "local",
        HARBORFIELD_REVIEW_ARTIFACT_ROOT: artifactRoot,
        ...(app.isPackaged ? { PATH: path.dirname(python) + ":" + (process.env.PATH ?? "") } : {}),
      },
      stdio: app.isPackaged ? ["pipe", "ignore", "ignore"] : "ignore",
    },
  );
  sidecar.once("exit", (code) => {
    if (app.isQuiting) return;
    console.error(`PortLog sidecar exited unexpectedly: ${code}`);
    for (const worker of activeInspections.values()) worker.kill("SIGTERM");
    app.quit();
  });
  await waitForSidecar();
}

async function stopSidecar() {
  await terminateChild(sidecar);
}

function projectDirectory() {
  return path.join(app.getPath("userData"), "current-project");
}

function legacyProjectDirectories() {
  if (process.env.PORTLOG_DESKTOP_USER_DATA_DIR) return [];
  const appData = app.getPath("appData");
  return [
    path.join(appData, "portlog-ui", "current-project"),
    path.join(appData, "Electron", "current-project"),
  ];
}

async function migrateLegacyProjectIfNeeded() {
  await migrateLegacyProject(projectDirectory(), legacyProjectDirectories());
}

async function persistImportedProject(_event, payload) {
  const sourcePath =
    typeof payload.sourcePath === "string" && payload.sourcePath.length > 0
      ? payload.sourcePath
      : await persistUploadedSource(payload);
  return persistLocalProject({
    projectDirectory: projectDirectory(),
    ...payload,
    sourcePath,
  });
}

async function persistUploadedSource(payload) {
  const filename =
    String(payload.filename ?? "source.xml").replace(/[^a-zA-Z0-9._-]+/g, "_") || "source.xml";
  const sourcePath = path.join(projectDirectory(), "sources", `${payload.sessionId}-${filename}`);
  await fs.mkdir(path.dirname(sourcePath), { recursive: true });
  await fs.writeFile(sourcePath, payload.sourceContent, { encoding: "utf8", mode: 0o600 });
  return sourcePath;
}
function desktopChatProviderStore() {
  return createDesktopChatProviderStore({ directory: app.getPath("userData") });
}

async function getSelectedChatProvider() {
  return desktopChatProviderStore().load();
}

async function setSelectedChatProvider(_event, provider) {
  return desktopChatProviderStore().save(provider ?? null);
}

async function loadCurrentProject() {
  try {
    await migrateLegacyProjectIfNeeded();
    return await loadLocalProject(projectDirectory());
  } catch (error) {
    return { error: error instanceof Error ? error.message : String(error) };
  }
}

async function runLocalInspection(event, payload) {
  await migrateLegacyProjectIfNeeded();
  const project = await loadLocalProject(projectDirectory());
  if (project.projectId !== payload.sessionId)
    throw new Error("The active review does not match the prepared local project");
  return runLocalTurn(event, payload, "inspection");
}

async function runLocalChat(event, payload) {
  return runLocalTurn(event, payload, "chat");
}

async function resolveLocalRuntime(requestedProvider) {
  let runtime;
  if (requestedProvider === "anthropic") {
    const auth = await getClaudeAuth();
    runtime = {
      provider: "anthropic",
      model: "claude-sonnet-4-5",
      apiKey: await auth.getAccessToken(),
      baseUrl: "https://api.anthropic.com",
    };
  }
  if (requestedProvider === "openai-codex") {
    const auth = await getCodexAuth();
    runtime = {
      provider: "openai-codex",
      model: "gpt-5.4",
      apiKey: await auth.getAccessToken(),
      baseUrl: "https://chatgpt.com/backend-api",
    };
  }
  if (!runtime) {
    openRouterEnv = resolveCurrentOpenRouterEnv();
    if (!openRouterEnv.configured || !openRouterEnv.credential)
      throw new Error("OpenRouter is not configured");
    runtime = {
      provider: "openrouter",
      model: "deepseek/deepseek-v4-flash",
      apiKey: openRouterEnv.credential,
      baseUrl: process.env.PORTLOG_OPENROUTER_BASE_URL ?? "https://openrouter.ai/api/v1",
    };
  }
  return runtime;
}

async function runLocalTurn(event, payload, mode) {
  const runtime = await resolveLocalRuntime(payload.provider ?? "openrouter");
  if (activeInspections.has(payload.turnId)) throw new Error("This desktop turn is already active");
  const worker = spawn(
    process.execPath,
    ["--experimental-strip-types", path.join(__dirname, "local-inspection-worker.ts")],
    {
      cwd: repoRootForLocalRuntime(),
      env: {
        ...process.env,
        ELECTRON_RUN_AS_NODE: "1",
        PORTLOG_RUNTIME_API_KEY: runtime.apiKey,
        PORTLOG_RUNTIME_PROVIDER: runtime.provider,
        PORTLOG_RUNTIME_MODEL: runtime.model,
        PORTLOG_RUNTIME_BASE_URL: runtime.baseUrl,
      },
      stdio: ["pipe", "pipe", "pipe"],
    },
  );
  activeInspections.set(payload.turnId, worker);
  worker.stdin.end(
    JSON.stringify({
      mode,
      projectDirectory: mode === "chat" ? undefined : projectDirectory(),
      cwd: repoRootForLocalRuntime(),
      sessionId: payload.sessionId,
      turnId: payload.turnId,
      question: payload.question,
      posture: payload.posture,
      provider: runtime.provider,
      model: runtime.model,
      baseUrl: runtime.baseUrl,
      sidecarEndpoint,
    }),
  );
  return new Promise((resolve, reject) => {
    let stdout = "";
    let stderr = "";
    let result;
    worker.stdout.on("data", (chunk) => {
      stdout += chunk;
      const lines = stdout.split("\n");
      stdout = lines.pop() ?? "";
      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const message = JSON.parse(line);
          if (message.kind === "event") {
            if (message.event?.type === "turn_started") worker.portlogStarted = true;
            event.sender.send("portlog:inspection-event", message);
          }
          if (message.kind === "result") result = message.record;
        } catch {
          stderr += "Invalid desktop worker output. ";
        }
      }
    });
    worker.stderr.on("data", (chunk) => {
      stderr += String(chunk).slice(0, 4000);
    });
    worker.once("error", reject);
    worker.once("exit", (code) => {
      activeInspections.delete(payload.turnId);
      if (result) resolve(result);
      else
        reject(
          new Error(
            code === 0
              ? "Desktop turn ended without a result"
              : `Desktop worker failed (${code}): ${redactRuntimeSecrets(stderr, runtime)}`,
          ),
        );
    });
  });
}

function redactRuntimeSecrets(message, runtime) {
  return [openRouterEnv?.credential, runtime?.apiKey]
    .filter((secret) => typeof secret === "string" && secret.length > 0)
    .reduce((text, secret) => text.split(secret).join("[REDACTED]"), message);
}

async function cancelLocalInspection(_event, turnId) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    const worker = activeInspections.get(turnId);
    if (worker && worker.exitCode === null && worker.portlogStarted) {
      worker.kill("SIGTERM");
      return { cancelled: true };
    }
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  return { cancelled: false };
}

async function selectDexpiSource(window) {
  const result = await dialog.showOpenDialog(window, {
    title: "Import DEXPI source",
    properties: ["openFile"],
    filters: [{ name: "DEXPI XML", extensions: ["xml"] }],
  });
  if (result.canceled || !result.filePaths[0]) return null;
  const sourcePath = result.filePaths[0];
  return {
    path: sourcePath,
    filename: path.basename(sourcePath),
    content: await fs.readFile(sourcePath, "utf8"),
  };
}

function createReviewWindow() {
  const window = new BrowserWindow({
    width: 1440,
    height: 960,
    minWidth: 1024,
    minHeight: 720,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      preload: path.join(__dirname, "preload.cjs"),
    },
  });
  void window.loadURL(new URL("/assistant", desktopUiUrl).toString());
  return window;
}

app.whenReady().then(async () => {
  if (!desktopUiUrl && !app.isPackaged) {
    console.error(
      "PORTLOG_DESKTOP_UI_URL is required; start the PortLog frontend before launching the desktop shell.",
    );
    app.exit(1);
    return;
  }
  try {
    await startPackagedUi();
    await startSidecar();
  } catch (error) {
    console.error(error);
    await stopSidecar().catch(() => undefined);
    await stopPackagedUi().catch(() => undefined);
    app.exit(1);
    return;
  }
  ipcMain.handle("portlog:select-dexpi-source", (event) =>
    selectDexpiSource(BrowserWindow.fromWebContents(event.sender)),
  );
  ipcMain.handle("portlog:persist-imported-project", persistImportedProject);
  ipcMain.handle("portlog:load-current-project", loadCurrentProject);
  ipcMain.handle("portlog:openrouter-status", openRouterStatus);
  ipcMain.handle("portlog:claude-auth-status", claudeAuthStatus);
  ipcMain.handle("portlog:claude-login", claudeLogin);
  ipcMain.handle("portlog:claude-cancel-login", claudeCancelLogin);
  ipcMain.handle("portlog:claude-logout", claudeLogout);
  ipcMain.handle("portlog:codex-auth-status", codexAuthStatus);
  ipcMain.handle("portlog:codex-login", (_event, method) => codexLogin(method));
  ipcMain.handle("portlog:codex-cancel-login", codexCancelLogin);
  ipcMain.handle("portlog:codex-logout", codexLogout);
  ipcMain.handle("portlog:get-selected-chat-provider", getSelectedChatProvider);
  ipcMain.handle("portlog:set-selected-chat-provider", setSelectedChatProvider);
  ipcMain.handle("portlog:check-openrouter", checkOpenRouterConnection);
  ipcMain.handle("portlog:run-local-inspection", runLocalInspection);
  ipcMain.handle("portlog:run-local-chat", runLocalChat);
  ipcMain.handle("portlog:cancel-local-inspection", cancelLocalInspection);
  createReviewWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createReviewWindow();
  });
});
app.on("before-quit", (event) => {
  if (app.isQuiting) return;
  event.preventDefault();
  app.isQuiting = true;
  for (const worker of activeInspections.values()) worker.kill("SIGTERM");
  void stopSidecar()
    .finally(() => stopPackagedUi())
    .finally(() => app.exit(0));
});
app.on("window-all-closed", () => {
  if (process.platform !== "darwin" || process.env.PORTLOG_QUIT_ON_WINDOW_ALL_CLOSED === "1")
    app.quit();
});

const fs = require("node:fs/promises");
const path = require("node:path");
const { spawn } = require("node:child_process");
const { app, BrowserWindow, dialog, ipcMain } = require("electron");
const { persistLocalProject, loadLocalProject } = require("./local-project-manifest.cjs");
const { resolveReviewSidecarPaths } = require("./electron-sidecar-paths.cjs");
const {
  resolveOpenRouterEnv,
  redactedOpenRouterState,
} = require("./electron-openrouter-config.cjs");
const {
  checkOpenRouterConnection: checkResolvedOpenRouterConnection,
} = require("./electron-openrouter-check.cjs");

const desktopUiUrl = process.env.PORTLOG_DESKTOP_UI_URL;
if (process.env.PORTLOG_DESKTOP_USER_DATA_DIR)
  app.setPath("userData", process.env.PORTLOG_DESKTOP_USER_DATA_DIR);
const sidecarEndpoint = "http://127.0.0.1:8000";
let sidecar;
let openRouterEnv;
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

function repoRootForLocalRuntime() {
  return resolveReviewSidecarPaths({
    isPackaged: app.isPackaged,
    resourcesPath: process.resourcesPath,
    desktopDir: __dirname,
  }).cwd;
}

function openRouterStatus() {
  if (!openRouterEnv)
    openRouterEnv = resolveOpenRouterEnv({
      appIsPackaged: app.isPackaged,
      repoRoot: repoRootForLocalRuntime(),
      env: process.env,
    });
  return redactedOpenRouterState(openRouterEnv);
}

async function checkOpenRouterConnection() {
  if (!openRouterEnv)
    openRouterEnv = resolveOpenRouterEnv({
      appIsPackaged: app.isPackaged,
      repoRoot: repoRootForLocalRuntime(),
      env: process.env,
    });
  return checkResolvedOpenRouterConnection({ resolved: openRouterEnv });
}

async function startSidecar() {
  try {
    if ((await fetch(`${sidecarEndpoint}/openapi.json`)).ok)
      throw new Error(
        `PortLog sidecar port 8000 is already in use; refuse to attach to an unowned process`,
      );
  } catch (error) {
    if (error instanceof Error && error.message.includes("already in use")) throw error;
  }
  const artifactRoot = path.join(app.getPath("userData"), "reviews");
  const { python, cwd } = resolveReviewSidecarPaths({
    isPackaged: app.isPackaged,
    resourcesPath: process.resourcesPath,
    desktopDir: __dirname,
  });
  sidecar = spawn(
    python,
    ["-m", "uvicorn", "pydexpi_datalog.web.asgi:app", "--host", "127.0.0.1", "--port", "8000"],
    {
      cwd,
      env: {
        ...process.env,
        HARBORFIELD_DEPLOYMENT_PROFILE: "local",
        HARBORFIELD_REVIEW_ARTIFACT_ROOT: artifactRoot,
      },
      stdio: "ignore",
    },
  );
  sidecar.once("exit", (code) => {
    if (code && !app.isQuiting) console.error(`PortLog sidecar exited: ${code}`);
  });
  await waitForSidecar();
}

async function stopSidecar() {
  if (!sidecar || sidecar.exitCode !== null) return;
  sidecar.kill("SIGTERM");
  await new Promise((resolve) => sidecar.once("exit", resolve));
}

function projectDirectory() {
  return path.join(app.getPath("userData"), "current-project");
}

async function persistImportedProject(_event, payload) {
  return persistLocalProject({ projectDirectory: projectDirectory(), ...payload });
}

async function loadCurrentProject() {
  try {
    return await loadLocalProject(projectDirectory());
  } catch (error) {
    return { error: error instanceof Error ? error.message : String(error) };
  }
}

async function runLocalInspection(event, payload) {
  const project = await loadLocalProject(projectDirectory());
  if (project.projectId !== payload.sessionId)
    throw new Error("The active review does not match the prepared local project");
  if (!openRouterEnv)
    openRouterEnv = resolveOpenRouterEnv({
      appIsPackaged: app.isPackaged,
      repoRoot: repoRootForLocalRuntime(),
      env: process.env,
    });
  if (!openRouterEnv.configured || !openRouterEnv.credential)
    throw new Error("OpenRouter is not configured");
  if (activeInspections.has(payload.turnId))
    throw new Error("This inspection turn is already active");
  const worker = spawn(
    process.execPath,
    ["--experimental-strip-types", path.join(__dirname, "local-inspection-worker.ts")],
    {
      cwd: repoRootForLocalRuntime(),
      env: {
        ...process.env,
        ELECTRON_RUN_AS_NODE: "1",
        PORTLOG_OPENROUTER_API_KEY: openRouterEnv.credential,
      },
      stdio: ["pipe", "pipe", "pipe"],
    },
  );
  activeInspections.set(payload.turnId, worker);
  worker.stdin.end(
    JSON.stringify({
      projectDirectory: projectDirectory(),
      sessionId: payload.sessionId,
      turnId: payload.turnId,
      question: payload.question,
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
          stderr += "Invalid inspection worker output. ";
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
              ? "Inspection ended without a result"
              : `Inspection worker failed (${code}): ${stderr.replace(openRouterEnv.credential, "[REDACTED]")}`,
          ),
        );
    });
  });
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
  if (!desktopUiUrl) {
    console.error(
      "PORTLOG_DESKTOP_UI_URL is required; start the PortLog frontend before launching the desktop shell.",
    );
    app.exit(1);
    return;
  }
  try {
    await startSidecar();
  } catch (error) {
    console.error(error);
    app.exit(1);
    return;
  }
  ipcMain.handle("portlog:select-dexpi-source", (event) =>
    selectDexpiSource(BrowserWindow.fromWebContents(event.sender)),
  );
  ipcMain.handle("portlog:persist-imported-project", persistImportedProject);
  ipcMain.handle("portlog:load-current-project", loadCurrentProject);
  ipcMain.handle("portlog:openrouter-status", openRouterStatus);
  ipcMain.handle("portlog:check-openrouter", checkOpenRouterConnection);
  ipcMain.handle("portlog:run-local-inspection", runLocalInspection);
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
  void stopSidecar().finally(() => app.exit(0));
});
app.on("window-all-closed", () => {
  if (process.platform !== "darwin" || process.env.PORTLOG_QUIT_ON_WINDOW_ALL_CLOSED === "1")
    app.quit();
});

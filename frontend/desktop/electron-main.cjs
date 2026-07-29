const fs = require("node:fs/promises");
const path = require("node:path");
const { spawn } = require("node:child_process");
const { app, BrowserWindow, dialog, ipcMain } = require("electron");
const { persistLocalProject, loadLocalProject } = require("./local-project-manifest.cjs");

const desktopUiUrl = process.env.PORTLOG_DESKTOP_UI_URL;
if (process.env.PORTLOG_DESKTOP_USER_DATA_DIR) app.setPath("userData", process.env.PORTLOG_DESKTOP_USER_DATA_DIR);
const sidecarEndpoint = "http://127.0.0.1:8000";
let sidecar;

async function waitForSidecar() {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (sidecar?.exitCode !== null) throw new Error(`PortLog sidecar exited before readiness: ${sidecar?.exitCode}`);
    try { if ((await fetch(`${sidecarEndpoint}/openapi.json`)).ok) return; } catch { /* starting */ }
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error("PortLog local review sidecar did not become ready within 5 seconds");
}

async function startSidecar() {
  try {
    if ((await fetch(`${sidecarEndpoint}/openapi.json`)).ok) throw new Error(`PortLog sidecar port 8000 is already in use; refuse to attach to an unowned process`);
  } catch (error) {
    if (error instanceof Error && error.message.includes("already in use")) throw error;
  }
  const artifactRoot = path.join(app.getPath("userData"), "reviews");
  const python = app.isPackaged
    ? path.join(process.resourcesPath, "review-sidecar", "python", "bin", "python")
    : path.resolve(__dirname, "../../.venv/bin/python");
  const cwd = app.isPackaged ? path.join(process.resourcesPath, "review-sidecar", "app") : path.resolve(__dirname, "../..");
  sidecar = spawn(python, ["-m", "uvicorn", "pydexpi_datalog.web.asgi:app", "--host", "127.0.0.1", "--port", "8000"], {
    cwd, env: { ...process.env, HARBORFIELD_DEPLOYMENT_PROFILE: "local", HARBORFIELD_REVIEW_ARTIFACT_ROOT: artifactRoot }, stdio: "ignore",
  });
  sidecar.once("exit", (code) => { if (code && !app.isQuiting) console.error(`PortLog sidecar exited: ${code}`); });
  await waitForSidecar();
}

async function stopSidecar() {
  if (!sidecar || sidecar.exitCode !== null) return;
  sidecar.kill("SIGTERM");
  await new Promise((resolve) => sidecar.once("exit", resolve));
}

function projectDirectory() { return path.join(app.getPath("userData"), "current-project"); }

async function persistImportedProject(_event, payload) {
  return persistLocalProject({ projectDirectory: projectDirectory(), ...payload });
}

async function loadCurrentProject() {
  try { return await loadLocalProject(projectDirectory()); } catch (error) { return { error: error instanceof Error ? error.message : String(error) }; }
}

async function selectDexpiSource(window) {
  const result = await dialog.showOpenDialog(window, { title: "Import DEXPI source", properties: ["openFile"], filters: [{ name: "DEXPI XML", extensions: ["xml"] }] });
  if (result.canceled || !result.filePaths[0]) return null;
  const sourcePath = result.filePaths[0];
  return { path: sourcePath, filename: path.basename(sourcePath), content: await fs.readFile(sourcePath, "utf8") };
}

function createReviewWindow() {
  const window = new BrowserWindow({ width: 1440, height: 960, minWidth: 1024, minHeight: 720, webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true, preload: path.join(__dirname, "preload.cjs") } });
  void window.loadURL(new URL("/assistant", desktopUiUrl).toString());
  return window;
}

app.whenReady().then(async () => {
  if (!desktopUiUrl) { console.error("PORTLOG_DESKTOP_UI_URL is required; start the PortLog frontend before launching the desktop shell."); app.exit(1); return; }
  try { await startSidecar(); } catch (error) { console.error(error); app.exit(1); return; }
  ipcMain.handle("portlog:select-dexpi-source", (event) => selectDexpiSource(BrowserWindow.fromWebContents(event.sender)));
  ipcMain.handle("portlog:persist-imported-project", persistImportedProject);
  ipcMain.handle("portlog:load-current-project", loadCurrentProject);
  createReviewWindow();
  app.on("activate", () => { if (BrowserWindow.getAllWindows().length === 0) createReviewWindow(); });
});
app.on("before-quit", (event) => {
  if (app.isQuiting) return;
  event.preventDefault();
  app.isQuiting = true;
  void stopSidecar().finally(() => app.exit(0));
});
app.on("window-all-closed", () => { if (process.platform !== "darwin" || process.env.PORTLOG_QUIT_ON_WINDOW_ALL_CLOSED === "1") app.quit(); });

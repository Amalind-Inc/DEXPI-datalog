const fs = require("node:fs/promises");
const path = require("node:path");
const { app, BrowserWindow, dialog, ipcMain } = require("electron");

const desktopUiUrl = process.env.PORTLOG_DESKTOP_UI_URL;

async function selectDexpiSource(window) {
  const result = await dialog.showOpenDialog(window, {
    title: "Import DEXPI source",
    properties: ["openFile"],
    filters: [{ name: "DEXPI XML", extensions: ["xml"] }],
  });
  if (result.canceled || !result.filePaths[0]) return null;
  const sourcePath = result.filePaths[0];
  return { path: sourcePath, filename: path.basename(sourcePath), content: await fs.readFile(sourcePath, "utf8") };
}

function createReviewWindow() {
  const window = new BrowserWindow({
    width: 1440, height: 960, minWidth: 1024, minHeight: 720,
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true, preload: path.join(__dirname, "preload.cjs") },
  });
  void window.loadURL(new URL("/assistant", desktopUiUrl).toString());
  return window;
}

app.whenReady().then(() => {
  if (!desktopUiUrl) { console.error("PORTLOG_DESKTOP_UI_URL is required; start the PortLog frontend before launching the desktop shell."); app.exit(1); return; }
  ipcMain.handle("portlog:select-dexpi-source", (event) => selectDexpiSource(BrowserWindow.fromWebContents(event.sender)));
  createReviewWindow();
  app.on("activate", () => { if (BrowserWindow.getAllWindows().length === 0) createReviewWindow(); });
});
app.on("window-all-closed", () => { if (process.platform !== "darwin") app.quit(); });

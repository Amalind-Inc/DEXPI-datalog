const fs = require("node:fs");
const { app, BrowserWindow } = require("electron");
const { resolveReviewSidecarPaths } = require("./electron-resource-path.cjs");

app.whenReady().then(() => {
  const sidecar = resolveReviewSidecarPaths(process.resourcesPath);
  if (!fs.existsSync(sidecar.python) || !fs.existsSync(sidecar.cwd)) {
    throw new Error("packaged review sidecar resources are missing");
  }
  const window = new BrowserWindow({ show: false });
  window.loadURL("data:text/html,PortLog Electron spike");
});

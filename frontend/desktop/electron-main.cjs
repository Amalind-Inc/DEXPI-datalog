const { app, BrowserWindow } = require("electron");

const desktopUiUrl = process.env.PORTLOG_DESKTOP_UI_URL;

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
    },
  });
  void window.loadURL(new URL("/assistant", desktopUiUrl).toString());
}

app.whenReady().then(() => {
  if (!desktopUiUrl) {
    console.error(
      "PORTLOG_DESKTOP_UI_URL is required; start the PortLog frontend before launching the desktop shell.",
    );
    app.exit(1);
    return;
  }

  createReviewWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createReviewWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("portlogDesktop", {
  selectDexpiSource: () => ipcRenderer.invoke("portlog:select-dexpi-source"),
});

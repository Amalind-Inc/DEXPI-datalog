const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("portlogDesktop", {
  selectDexpiSource: () => ipcRenderer.invoke("portlog:select-dexpi-source"),
  persistImportedProject: (payload) =>
    ipcRenderer.invoke("portlog:persist-imported-project", payload),
  loadCurrentProject: () => ipcRenderer.invoke("portlog:load-current-project"),
  openRouterStatus: () => ipcRenderer.invoke("portlog:openrouter-status"),
  checkOpenRouter: () => ipcRenderer.invoke("portlog:check-openrouter"),
  runLocalInspection: (payload) => ipcRenderer.invoke("portlog:run-local-inspection", payload),
  cancelLocalInspection: (turnId) => ipcRenderer.invoke("portlog:cancel-local-inspection", turnId),
  onInspectionEvent: (listener) => {
    const handler = (_event, message) => listener(message);
    ipcRenderer.on("portlog:inspection-event", handler);
    return () => ipcRenderer.removeListener("portlog:inspection-event", handler);
  },
});

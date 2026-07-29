import assert from "node:assert/strict";
import test from "node:test";

import { resolveReviewSidecarPaths } from "./electron-sidecar-paths.cjs";

test("production Electron resolves packaged review sidecar resources", () => {
  assert.deepEqual(
    resolveReviewSidecarPaths({ isPackaged: true, resourcesPath: "/Applications/PortLog.app/Contents/Resources", desktopDir: "/repo/frontend/desktop" }),
    {
      python: "/Applications/PortLog.app/Contents/Resources/review-sidecar/python/bin/python",
      cwd: "/Applications/PortLog.app/Contents/Resources/review-sidecar/app",
    },
  );
});

test("production Electron resolves checkout review sidecar resources during development", () => {
  assert.deepEqual(
    resolveReviewSidecarPaths({ isPackaged: false, resourcesPath: "/unused", desktopDir: "/repo/frontend/desktop" }),
    { python: "/repo/.venv/bin/python", cwd: "/repo" },
  );
});

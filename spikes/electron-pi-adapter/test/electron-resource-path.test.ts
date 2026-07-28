import assert from "node:assert/strict";
import test from "node:test";

import { resolveReviewSidecarPaths } from "../src/electron-resource-path.ts";

test("uses Electron resourcesPath for packaged macOS sidecars", () => {
  assert.deepEqual(
    resolveReviewSidecarPaths({
      isPackaged: true,
      resourcesPath: "/Applications/PortLog.app/Contents/Resources",
      devRoot: "/repo/spikes/electron-pi-adapter",
    }),
    {
      python: "/Applications/PortLog.app/Contents/Resources/review-sidecar/python/bin/python",
      cwd: "/Applications/PortLog.app/Contents/Resources/review-sidecar/app",
    },
  );
});

test("uses the checked-out sidecar layout during development", () => {
  assert.deepEqual(
    resolveReviewSidecarPaths({
      isPackaged: false,
      resourcesPath: "/ignored",
      devRoot: "/repo/spikes/electron-pi-adapter",
    }),
    {
      python: "/repo/spikes/electron-pi-adapter/review-sidecar/python/bin/python",
      cwd: "/repo/spikes/electron-pi-adapter/review-sidecar/app",
    },
  );
});

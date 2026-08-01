import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";
import test from "node:test";

const require = createRequire(import.meta.url);
const config = require("./electron-builder.config.cjs") as {
  files: string[];
  directories: { app: string };
  extraResources: Array<{ from: string; to: string }>;
  mac: {
    target: Array<{ target: string; arch: string[] }>;
    minimumSystemVersion: string;
    identity: string;
    hardenedRuntime: boolean;
    signIgnore: string;
    strictVerify: boolean;
  };
};

test("macOS release configuration packages the staged arm64 DMG candidate", () => {
  assert.deepEqual(config.files, ["**/*"]);
  assert.deepEqual(config.mac.target, [
    { target: "dmg", arch: ["arm64"] },
    { target: "dir", arch: ["arm64"] },
  ]);
  assert.equal(config.mac.minimumSystemVersion, "14.0.0");
  assert.equal(config.mac.identity, "-");
  assert.equal(config.mac.hardenedRuntime, false);
  assert.equal(config.mac.signIgnore, "review-sidecar|Python\\.framework");
  assert.equal(config.mac.strictVerify, false);
  assert.equal(config.directories.app, "release/electron-app");
});

test("macOS release configuration carries UI and deterministic sidecar resources", () => {
  assert.deepEqual(
    config.extraResources,
    [
      { from: "release/stage/ui", to: "ui" },
      { from: "release/stage/review-sidecar", to: "review-sidecar" },
      { from: "release/release-manifest.json", to: "release-manifest.json" },
    ],
  );
});

test("a completed release stage has no host-runtime dependency", { skip: !process.env.PORTLOG_RELEASE_STAGE }, () => {
  const stage = process.env.PORTLOG_RELEASE_STAGE!;
  assert.ok(existsSync(join(stage, "ui", "server.js")));
  assert.ok(existsSync(join(stage, "ui", "runtime", "next", "package.json")));
  assert.ok(existsSync(join(stage, "review-sidecar", "python", "bin", "python")));
  assert.ok(existsSync(join(stage, "review-sidecar", "python", "bin", "souffle")));
});

test("a completed Electron app stage includes both provider auth modules", { skip: !process.env.PORTLOG_ELECTRON_APP }, () => {
  const app = process.env.PORTLOG_ELECTRON_APP!;
  assert.ok(existsSync(join(app, "package.json")));
  assert.ok(existsSync(join(app, "desktop", "provider-auth-controller.cjs")));
  assert.ok(existsSync(join(app, "desktop", "provider-keychain.cjs")));
});

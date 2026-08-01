import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { readFile, readdir, rm, stat, writeFile } from "node:fs/promises";
import { execFile as execFileCallback } from "node:child_process";
import { promisify } from "node:util";
import path from "node:path";
import { createRequire } from "node:module";

const root = path.resolve(import.meta.dirname, "..");
const frontend = path.join(root, "frontend");
const release = path.join(frontend, "release");
const app = path.join(release, "dist", "mac-arm64", "PortLog.app");
const appBinary = path.join(app, "Contents", "MacOS", "PortLog");
const resources = path.join(app, "Contents", "Resources");
const appStage = path.join(release, "electron-app");
const stage = path.join(release, "stage");
const userData = path.join(root, ".tmp", "release-acceptance-userData");
const requireFromFrontend = createRequire(path.join(frontend, "package.json"));
const cleanEnv = {
  PATH: "/usr/bin:/bin:/usr/sbin:/sbin",
  HOME: process.env.HOME ?? "/tmp/portlog-clean-home",
  TMPDIR: process.env.TMPDIR ?? "/tmp",
  LANG: "en_US.UTF-8",
};
const { _electron } = requireFromFrontend("playwright");
const execFile = promisify(execFileCallback);
const builderConfig = requireFromFrontend("./desktop/electron-builder.config.cjs");

function assertFile(file) {
  assert.ok(existsSync(file), `Expected release file: ${file}`);
}

async function assertArm64Executable(file) {
  const { stdout } = await execFile("file", [file]);
  assert.match(stdout, /\barm64\b/, `Expected an arm64 executable: ${file}`);
}

async function directorySize(directory) {
  let total = 0;
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const entryPath = path.join(directory, entry.name);
    total += entry.isDirectory() ? await directorySize(entryPath) : (await stat(entryPath)).size;
  }
  return total;
}

async function waitForSidecar() {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try {
      if ((await fetch("http://127.0.0.1:8000/openapi.json")).ok) return;
    } catch {
      /* packaged Electron is still starting its supervised sidecar */
    }
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error("Packaged sidecar did not answer its loopback health endpoint");
}

for (const file of [
  appBinary,
  path.join(resources, "ui", "server.js"),
  path.join(resources, "ui", "runtime", "next", "package.json"),
  path.join(resources, "review-sidecar", "python", "bin", "python"),
  path.join(resources, "review-sidecar", "python", "bin", "souffle"),
  path.join(resources, "release-manifest.json"),
  path.join(appStage, "desktop", "provider-auth-controller.cjs"),
  path.join(appStage, "desktop", "provider-keychain.cjs"),
])
  assertFile(file);

const releaseManifest = JSON.parse(await readFile(path.join(resources, "release-manifest.json"), "utf8"));
assert.equal(releaseManifest.minimum_macos, builderConfig.mac.minimumSystemVersion);
assert.deepEqual(releaseManifest.supported_architectures, ["arm64"]);
assert.equal(releaseManifest.notarized, false);

await Promise.all([
  assertArm64Executable(appBinary),
  assertArm64Executable(path.join(resources, "review-sidecar", "python", "bin", "python")),
  assertArm64Executable(path.join(resources, "review-sidecar", "python", "bin", "souffle")),
]);

for (const file of [
  path.join(stage, "ui", "server.js"),
  path.join(stage, "ui", "runtime", "next", "package.json"),
  path.join(stage, "review-sidecar", "python", "bin", "python"),
  path.join(stage, "review-sidecar", "python", "bin", "souffle"),
])
  assertFile(file);

await rm(userData, { recursive: true, force: true });
const launchStarted = Date.now();
const instance = await _electron.launch({
  executablePath: appBinary,
  args: [],
  env: {
    ...cleanEnv,
    PORTLOG_DESKTOP_USER_DATA_DIR: userData,
    PORTLOG_QUIT_ON_WINDOW_ALL_CLOSED: "1",
    HARBORFIELD_DISABLE_BYOK: "1",
  },
});
const packagedStderr = [];
instance.process().stderr?.on("data", (chunk) => packagedStderr.push(String(chunk)));
try {
  const window = await instance.firstWindow();
  await window.getByRole("region", { name: "Chat" }).waitFor({ state: "visible", timeout: 30_000 });
  await waitForSidecar();
  assert.equal(await window.title(), "PortLog · Harborfield");
  const measurements = {
    ok: true,
    app,
    ui: "packaged",
    sidecar: "bundled",
    clean_environment: true,
    startup_ms: Date.now() - launchStarted,
    app_size_bytes: await directorySize(app),
  };
  await writeFile(path.join(release, "acceptance-results.json"), `${JSON.stringify(measurements, null, 2)}\n`);
  console.log(JSON.stringify(measurements));
} catch (error) {
  console.error(packagedStderr.join(""));
  throw error;
} finally {
  await instance.close();
  await rm(userData, { recursive: true, force: true });
}

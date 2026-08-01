import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { execFile } from "node:child_process";
import { promisify } from "node:util";

const run = promisify(execFile);
const root = path.resolve(import.meta.dirname, "..");
const frontend = path.join(root, "frontend");
const require = createRequire(import.meta.url);
const minimumSystemVersion = require(path.join(frontend, "desktop/electron-builder.config.cjs")).mac.minimumSystemVersion;
const release = path.join(frontend, "release");
const stage = path.join(release, "stage");
const sidecarStage = path.join(stage, "review-sidecar");
const pythonBuild = path.join(release, "python-build");
const pythonDist = path.join(pythonBuild, "dist");
const pythonWork = path.join(pythonBuild, "work");
const pythonSpec = path.join(pythonBuild, "spec");
const electronApp = path.join(release, "electron-app");
const python = path.join(root, ".venv", "bin", "python");
const souffle = process.env.PORTLOG_SOUFFLE_PATH ?? "/opt/homebrew/bin/souffle";
const runtimeFiles = [
  "electron-main.cjs",
  "preload.cjs",
  "electron-sidecar-paths.cjs",
  "electron-openrouter-config.cjs",
  "electron-openrouter-check.cjs",
  "claude-auth-controller.cjs",
  "claude-keychain.cjs",
  "codex-auth-controller.cjs",
  "codex-keychain.cjs",
  "desktop-chat-provider.cjs",
  "provider-auth-controller.cjs",
  "provider-keychain.cjs",
  "local-project-manifest.cjs",
  "local-inspection-worker.ts",
  "local-review-inspection.ts",
  "pi-turn-adapter.ts",
];

async function command(file, args, options) {
  console.log(`$ ${file} ${args.join(" ")}`);
  await run(file, args, { ...options, maxBuffer: 32 * 1024 * 1024 });
}

async function main() {
  if (process.platform !== "darwin")
    throw new Error("The PortLog macOS release candidate must be built on macOS.");
  if (process.arch !== "arm64")
    throw new Error(`The arm64 release candidate requires an arm64 builder, got ${process.arch}.`);
  const { stdout: macVersionOutput } = await run("sw_vers", ["-productVersion"]);
  const macMajor = Number.parseInt(macVersionOutput.trim().split(".")[0] ?? "0", 10);
  const minimumMacMajor = Number.parseInt(minimumSystemVersion.split(".")[0] ?? "0", 10);
  if (!Number.isFinite(macMajor) || macMajor < minimumMacMajor)
    throw new Error(`The PortLog release candidate requires macOS ${minimumSystemVersion} or newer, got ${macVersionOutput.trim()}.`);
  if (!existsSync(python)) throw new Error(`Missing project virtualenv Python: ${python}`);
  if (!existsSync(souffle))
    throw new Error(`Missing arm64 Soufflé binary: ${souffle}. Set PORTLOG_SOUFFLE_PATH to override.`);

  await rm(release, { recursive: true, force: true });
  await mkdir(stage, { recursive: true });

  const packageJson = JSON.parse(await readFile(path.join(frontend, "package.json"), "utf8"));
  await command("npm", ["run", "build"], { cwd: frontend, env: process.env });
  const standalone = path.join(frontend, ".next", "standalone");
  if (!existsSync(path.join(standalone, "server.js")))
    throw new Error("Next standalone output is missing server.js.");
  await cp(standalone, path.join(stage, "ui"), { recursive: true });
  await rm(path.join(stage, "ui", "node_modules"), { recursive: true, force: true });
  await cp(path.join(standalone, "node_modules"), path.join(stage, "ui", "runtime"), {
    recursive: true,
    dereference: true,
  });
  for (const optionalImageModule of ["sharp", "@img"])
    await rm(path.join(stage, "ui", "runtime", optionalImageModule), { recursive: true, force: true });
  const nextStatic = path.join(frontend, ".next", "static");
  if (existsSync(nextStatic)) await cp(nextStatic, path.join(stage, "ui", ".next", "static"), { recursive: true });
  const publicDir = path.join(frontend, "public");
  if (existsSync(publicDir)) await cp(publicDir, path.join(stage, "ui", "public"), { recursive: true });

  await command(
    python,
    [
      "-m",
      "PyInstaller",
      "--noconfirm",
      "--clean",
      "--onedir",
      "--name",
      "python",
      "--distpath",
      pythonDist,
      "--workpath",
      pythonWork,
      "--specpath",
      pythonSpec,
      "--paths",
      root,
      "--paths",
      path.join(root, "pyDEXPI"),
      "--hidden-import",
      "pydexpi_datalog.web.asgi",
      "--hidden-import",
      "pydexpi_datalog.web.review_api",
      "--collect-data",
      "pydexpi_datalog",
      "--collect-data",
      "pydexpi",
      "--exclude-module",
      "boto3",
      "--exclude-module",
      "botocore",
      path.join(root, "scripts", "packaged-sidecar.py"),
    ],
    { cwd: root, env: process.env },
  );
  await mkdir(path.join(sidecarStage, "python", "bin"), { recursive: true });
  await cp(path.join(pythonDist, "python"), path.join(sidecarStage, "python", "bin"), {
    recursive: true,
  });
  await cp(souffle, path.join(sidecarStage, "python", "bin", "souffle"));
  if (existsSync(path.join(sidecarStage, "python", "bin", "_internal", "botocore")))
    throw new Error("Local release sidecar must not include hosted botocore modules.");

  await mkdir(path.join(electronApp, "desktop"), { recursive: true });
  for (const runtimeFile of runtimeFiles) {
    await cp(path.join(frontend, "desktop", runtimeFile), path.join(electronApp, "desktop", runtimeFile));
  }
  await writeFile(
    path.join(electronApp, "package.json"),
    `${JSON.stringify(
      {
        name: "portlog-desktop-runtime",
        version: packageJson.version,
        private: true,
        main: "desktop/electron-main.cjs",
        dependencies: {
          "@earendil-works/pi-agent-core": "0.80.6",
          "@earendil-works/pi-ai": "0.80.6",
          typebox: packageJson.dependencies.typebox,
        },
      },
      null,
      2,
    )}\n`,
  );
  await command("npm", ["install", "--omit=dev", "--package-lock=false"], {
    cwd: electronApp,
    env: process.env,
  });
  await command("node", [path.join(root, "scripts", "patch-pi-oauth-page.mjs"), electronApp], {
    cwd: root,
    env: process.env,
  });

  const releaseManifest = {
    product: "PortLog",
    version: packageJson.version,
    platform: process.platform,
    arch: process.arch,
    minimum_macos: minimumSystemVersion,
    supported_architectures: ["arm64"],
    node: "Electron embedded runtime",
    python: "PyInstaller-frozen local sidecar",
    souffle: "bundled arm64 binary",
    signing: "ad-hoc/unsigned directory candidate; not notarized",
    notarized: false,
  };
  await writeFile(
    path.join(release, "release-manifest.json"),
    `${JSON.stringify(releaseManifest, null, 2)}\n`,
  );

  await command(
    "npx",
    ["electron-builder", "--config", "desktop/electron-builder.config.cjs", "--publish", "never"],
    { cwd: frontend, env: { ...process.env, CSC_IDENTITY_AUTO_DISCOVERY: "false" } },
  );
  console.log(`Release candidate written to ${path.join(release, "dist")}`);
}

await main();

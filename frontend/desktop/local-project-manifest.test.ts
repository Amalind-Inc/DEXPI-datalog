import assert from "node:assert/strict";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { loadLocalProject, migrateLegacyProject, persistLocalProject } from "./local-project-manifest.cjs";

test("Electron import persists a durable PortLog project manifest for reopen", async () => {
  const root = await mkdtemp(join(tmpdir(), "portlog-electron-manifest-"));
  const sourcePath = join(root, "E06.xml");
  const sourceContent = "<PlantModel />";
  await writeFile(sourcePath, sourceContent);
  try {
    const written = await persistLocalProject({ projectDirectory: join(root, "project"), sourcePath, sourceContent, sessionId: "pid-session", filename: "E06.xml", status: "ready", artifacts: { topology: "backend:pid-session/topology" } });
    const loaded = await loadLocalProject(join(root, "project"));
    assert.equal(loaded.projectId, "pid-session");
    assert.equal(loaded.source.filename, "E06.xml");
    assert.equal(loaded.source.digest, written.source.digest);
    assert.deepEqual(loaded.artifacts, { topology: "backend:pid-session/topology" });
  } finally { await rm(root, { recursive: true, force: true }); }
});

test("Electron migrates a valid development manifest over a corrupt stable manifest", async () => {
  const root = await mkdtemp(join(tmpdir(), "portlog-electron-migration-"));
  const sourcePath = join(root, "E07.xml");
  const legacyDirectory = join(root, "portlog-ui", "current-project");
  const stableDirectory = join(root, "PortLog", "current-project");
  await writeFile(sourcePath, "<PlantModel />");
  try {
    await persistLocalProject({
      projectDirectory: legacyDirectory,
      sourcePath,
      sourceContent: "<PlantModel />",
      sessionId: "pid-session",
      filename: "E07.xml",
      status: "ready",
    });
    await mkdir(stableDirectory, { recursive: true });
    await writeFile(join(stableDirectory, "portlog-project.json"), "{broken");
    assert.equal(await migrateLegacyProject(stableDirectory, [legacyDirectory]), true);
    assert.equal(await migrateLegacyProject(stableDirectory, [legacyDirectory]), false);
    const loaded = await loadLocalProject(stableDirectory);
    assert.equal(loaded.projectId, "pid-session");
    assert.equal(loaded.source.filename, "E07.xml");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("Electron reopen reports a missing original source as re-import recovery", async () => {
  const root = await mkdtemp(join(tmpdir(), "portlog-electron-missing-"));
  const sourcePath = join(root, "missing.xml");
  await writeFile(sourcePath, "<PlantModel />");
  try {
    await persistLocalProject({ projectDirectory: join(root, "project"), sourcePath, sourceContent: "<PlantModel />", sessionId: "pid-session", filename: "missing.xml", status: "ready" });
    await rm(sourcePath);
    await assert.rejects(loadLocalProject(join(root, "project")), /original DEXPI source is missing.*re-import/i);
  } finally { await rm(root, { recursive: true, force: true }); }
});

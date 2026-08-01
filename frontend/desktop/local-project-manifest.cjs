const crypto = require("node:crypto");
const fs = require("node:fs/promises");
const path = require("node:path");

const MANIFEST_FILE = "portlog-project.json";
const SCHEMA_VERSION = 2;

async function writeManifest(projectDirectory, manifest) {
  await fs.mkdir(projectDirectory, { recursive: true });
  const target = path.join(projectDirectory, MANIFEST_FILE);
  const temporary = path.join(projectDirectory, `.${MANIFEST_FILE}.${crypto.randomUUID()}.tmp`);
  await fs.writeFile(temporary, `${JSON.stringify(manifest, null, 2)}\n`, { mode: 0o600 });
  await fs.rename(temporary, target);
  return manifest;
}

async function persistLocalProject({
  projectDirectory,
  sourcePath,
  sourceContent,
  sessionId,
  filename,
  status,
  artifacts = {},
}) {
  const manifest = {
    schemaVersion: SCHEMA_VERSION,
    projectId: sessionId,
    source: {
      path: sourcePath,
      filename,
      digest: `sha256:${crypto.createHash("sha256").update(sourceContent).digest("hex")}`,
    },
    preparation: {
      status,
      digest: `sha256:${crypto.createHash("sha256").update(JSON.stringify(artifacts)).digest("hex")}`,
    },
    artifacts,
    reviewIds: [sessionId],
    turns: [],
  };
  return writeManifest(projectDirectory, manifest);
}

async function readManifest(projectDirectory) {
  const manifestPath = path.join(projectDirectory, MANIFEST_FILE);
  let manifest;
  try {
    manifest = JSON.parse(await fs.readFile(manifestPath, "utf8"));
  } catch (error) {
    throw new Error(
      `PortLog project manifest is corrupt or unavailable; re-import the DEXPI source (${manifestPath}): ${error instanceof Error ? error.message : String(error)}`,
    );
  }
  if (
    !manifest ||
    ![1, SCHEMA_VERSION].includes(manifest.schemaVersion) ||
    typeof manifest.projectId !== "string" ||
    !manifest.source ||
    typeof manifest.source.path !== "string"
  ) {
    throw new Error(
      `PortLog project manifest is corrupt; re-import the DEXPI source (${manifestPath})`,
    );
  }
  return manifest.schemaVersion === 1
    ? { ...manifest, schemaVersion: SCHEMA_VERSION, turns: [] }
    : { ...manifest, turns: Array.isArray(manifest.turns) ? manifest.turns : [] };
}

async function migrateLegacyProject(projectDirectory, legacyProjectDirectories) {
  const target = path.join(projectDirectory, MANIFEST_FILE);
  try {
    JSON.parse(await fs.readFile(target, "utf8"));
    return false;
  } catch {
    /* The stable location is missing or invalid; try a legacy copy. */
  }
  for (const legacyDirectory of legacyProjectDirectories) {
    const source = path.join(legacyDirectory, MANIFEST_FILE);
    try {
      const content = await fs.readFile(source, "utf8");
      JSON.parse(content);
      await fs.mkdir(projectDirectory, { recursive: true });
      const temporary = path.join(
        projectDirectory,
        `.${MANIFEST_FILE}.${crypto.randomUUID()}.migration.tmp`,
      );
      await fs.writeFile(temporary, content, { mode: 0o600 });
      await fs.rename(temporary, target);
      return true;
    } catch {
      /* Try the next legacy location. */
    }
  }
  return false;
}

async function loadLocalProject(projectDirectory) {
  const manifest = await readManifest(projectDirectory);
  try {
    await fs.access(manifest.source.path);
  } catch {
    throw new Error(
      `PortLog original DEXPI source is missing; re-import it to recover this review (${manifest.source.path})`,
    );
  }
  return manifest;
}

async function upsertLocalTurn(projectDirectory, turn) {
  const manifest = await readManifest(projectDirectory);
  const index = manifest.turns.findIndex(
    (candidate) => candidate && candidate.turnId === turn.turnId,
  );
  const turns = [...manifest.turns];
  if (index === -1) turns.push(turn);
  else turns[index] = turn;
  return writeManifest(projectDirectory, { ...manifest, schemaVersion: SCHEMA_VERSION, turns });
}

module.exports = {
  MANIFEST_FILE,
  migrateLegacyProject,
  persistLocalProject,
  loadLocalProject,
  upsertLocalTurn,
};

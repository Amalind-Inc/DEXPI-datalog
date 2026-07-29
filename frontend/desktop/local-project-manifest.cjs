const crypto = require("node:crypto");
const fs = require("node:fs/promises");
const path = require("node:path");

const MANIFEST_FILE = "portlog-project.json";
const SCHEMA_VERSION = 1;

async function persistLocalProject({ projectDirectory, sourcePath, sourceContent, sessionId, filename, status, artifacts = {} }) {
  await fs.mkdir(projectDirectory, { recursive: true });
  const manifest = {
    schemaVersion: SCHEMA_VERSION,
    projectId: sessionId,
    source: {
      path: sourcePath,
      filename,
      digest: `sha256:${crypto.createHash("sha256").update(sourceContent).digest("hex")}`,
    },
    preparation: { status, digest: `sha256:${crypto.createHash("sha256").update(JSON.stringify(artifacts)).digest("hex")}` },
    artifacts,
    reviewIds: [sessionId],
  };
  const target = path.join(projectDirectory, MANIFEST_FILE);
  const temporary = path.join(projectDirectory, `.${MANIFEST_FILE}.${crypto.randomUUID()}.tmp`);
  await fs.writeFile(temporary, `${JSON.stringify(manifest, null, 2)}\n`, { mode: 0o600 });
  await fs.rename(temporary, target);
  return manifest;
}

async function loadLocalProject(projectDirectory) {
  const manifestPath = path.join(projectDirectory, MANIFEST_FILE);
  let manifest;
  try {
    manifest = JSON.parse(await fs.readFile(manifestPath, "utf8"));
  } catch (error) {
    throw new Error(`PortLog project manifest is corrupt or unavailable; re-import the DEXPI source (${manifestPath}): ${error instanceof Error ? error.message : String(error)}`);
  }
  if (!manifest || manifest.schemaVersion !== SCHEMA_VERSION || typeof manifest.projectId !== "string" || !manifest.source || typeof manifest.source.path !== "string") {
    throw new Error(`PortLog project manifest is corrupt; re-import the DEXPI source (${manifestPath})`);
  }
  try {
    await fs.access(manifest.source.path);
  } catch {
    throw new Error(`PortLog original DEXPI source is missing; re-import it to recover this review (${manifest.source.path})`);
  }
  return manifest;
}

module.exports = { MANIFEST_FILE, persistLocalProject, loadLocalProject };

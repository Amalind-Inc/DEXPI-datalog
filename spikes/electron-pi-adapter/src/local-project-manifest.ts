import { createHash, randomUUID } from "node:crypto";
import { readFile, rename, writeFile } from "node:fs/promises";
import { basename, join } from "node:path";

const MANIFEST_FILE = "portlog-project.json";
const SCHEMA_VERSION = 1;

export interface LocalReviewProject {
  schemaVersion: 1;
  projectId: string;
  source: { path: string; digest: string };
  preparation: { digest: string; status: "ready" | "failed" };
  artifacts: Record<string, string>;
  reviewIds: string[];
}

export interface CreateLocalReviewProjectInput {
  projectDirectory: string;
  sourcePath: string;
  preparation: LocalReviewProject["preparation"];
  artifacts: Record<string, string>;
  reviewIds: string[];
}

export async function createLocalReviewProject(input: CreateLocalReviewProjectInput): Promise<LocalReviewProject> {
  const sourceContents = await readFile(input.sourcePath);
  const project: LocalReviewProject = {
    schemaVersion: SCHEMA_VERSION,
    projectId: randomUUID(),
    source: { path: input.sourcePath, digest: `sha256:${createHash("sha256").update(sourceContents).digest("hex")}` },
    preparation: input.preparation,
    artifacts: input.artifacts,
    reviewIds: input.reviewIds,
  };
  const manifestPath = join(input.projectDirectory, MANIFEST_FILE);
  const temporaryPath = join(input.projectDirectory, `.${MANIFEST_FILE}.${randomUUID()}.tmp`);
  await writeFile(temporaryPath, `${JSON.stringify(project, null, 2)}\n`, { mode: 0o600 });
  await rename(temporaryPath, manifestPath);
  return project;
}

export async function loadLocalReviewProject(projectDirectory: string): Promise<LocalReviewProject> {
  const manifestPath = join(projectDirectory, MANIFEST_FILE);
  let parsed: unknown;
  try {
    parsed = JSON.parse(await readFile(manifestPath, "utf8"));
  } catch (error) {
    throw new Error(`PortLog project manifest is corrupt or unavailable; restore from a backup or re-import the original DEXPI source (${manifestPath}): ${error instanceof Error ? error.message : String(error)}`);
  }
  if (!isProject(parsed)) {
    throw new Error(`PortLog project manifest is corrupt; restore from a backup or re-import the original DEXPI source (${manifestPath})`);
  }
  return parsed;
}

function isProject(value: unknown): value is LocalReviewProject {
  if (!isRecord(value) || value.schemaVersion !== SCHEMA_VERSION || !isString(value.projectId) || !isRecord(value.source) || !isString(value.source.path) || !isString(value.source.digest) || !isRecord(value.preparation) || !isString(value.preparation.digest) || (value.preparation.status !== "ready" && value.preparation.status !== "failed") || !isRecord(value.artifacts) || !Array.isArray(value.reviewIds) || !value.reviewIds.every(isString)) return false;
  return Object.entries(value.artifacts).every(([name, artifact]) => basename(name) === name && isString(artifact));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isString(value: unknown): value is string {
  return typeof value === "string";
}

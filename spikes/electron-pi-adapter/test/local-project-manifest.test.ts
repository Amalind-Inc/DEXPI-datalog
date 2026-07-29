import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { createLocalReviewProject, loadLocalReviewProject } from "../src/local-project-manifest.ts";

test("persists a prepared DEXPI review for reopen by stable project ID", async () => {
  const directory = await mkdtemp(join(tmpdir(), "portlog-local-project-"));
  const source = join(directory, "source.dexpi.xml");
  await writeFile(source, "<PlantModel />");

  try {
    const created = await createLocalReviewProject({
      projectDirectory: directory,
      sourcePath: source,
      preparation: { digest: "sha256:prepared", status: "ready" },
      artifacts: { drawing: "artifacts/drawing.json", topology: "artifacts/topology.json" },
      reviewIds: ["review-1"],
    });
    const reopened = await loadLocalReviewProject(directory);

    assert.equal(reopened.projectId, created.projectId);
    assert.equal(reopened.source.path, source);
    assert.equal(reopened.preparation.digest, "sha256:prepared");
    assert.deepEqual(reopened.artifacts, { drawing: "artifacts/drawing.json", topology: "artifacts/topology.json" });
    assert.deepEqual(reopened.reviewIds, ["review-1"]);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test("refuses corrupt project state with an actionable recovery error", async () => {
  const directory = await mkdtemp(join(tmpdir(), "portlog-corrupt-project-"));
  await writeFile(join(directory, "portlog-project.json"), "not json");
  try {
    await assert.rejects(loadLocalReviewProject(directory), /PortLog project manifest is corrupt.*restore/i);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

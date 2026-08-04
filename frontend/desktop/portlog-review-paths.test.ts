import assert from "node:assert/strict";
import { mkdir, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { resolveReviewArtifactRoot } from "./portlog-review-paths.ts";

test("an explicit artifact root wins over Electron discovery", async () => {
  const root = await mkdtemp(join(tmpdir(), "portlog-review-paths-"));
  try {
    const projectDirectory = join(root, "current-project");
    const siblingReviews = join(root, "reviews", "local");
    await mkdir(siblingReviews, { recursive: true });
    assert.equal(
      await resolveReviewArtifactRoot(projectDirectory, join(root, "explicit")),
      join(root, "explicit"),
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("an Electron current-project reuses its sibling reviews store", async () => {
  const root = await mkdtemp(join(tmpdir(), "portlog-review-paths-"));
  try {
    const projectDirectory = join(root, "current-project");
    const siblingReviews = join(root, "reviews");
    await mkdir(join(siblingReviews, "local"), { recursive: true });
    assert.equal(await resolveReviewArtifactRoot(projectDirectory, ""), siblingReviews);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("an ordinary project keeps its project-local artifact store", async () => {
  const root = await mkdtemp(join(tmpdir(), "portlog-review-paths-"));
  try {
    const projectDirectory = join(root, "prepared-project");
    await mkdir(join(root, "reviews", "local"), { recursive: true });
    assert.equal(
      await resolveReviewArtifactRoot(projectDirectory, ""),
      join(projectDirectory, ".portlog-artifacts"),
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

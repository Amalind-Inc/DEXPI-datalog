import { access, constants } from "node:fs/promises";
import { basename, dirname, join } from "node:path";

export async function resolveReviewArtifactRoot(
  projectDirectory: string,
  configuredRoot = process.env.PORTLOG_REVIEW_ARTIFACT_ROOT,
): Promise<string> {
  const configured = configuredRoot?.trim();
  if (configured) return configured;
  if (basename(projectDirectory) !== "current-project")
    return join(projectDirectory, ".portlog-artifacts");

  const electronArtifactRoot = join(dirname(projectDirectory), "reviews");
  try {
    await access(join(electronArtifactRoot, "local"), constants.R_OK);
    return electronArtifactRoot;
  } catch {
    return join(projectDirectory, ".portlog-artifacts");
  }
}

const path = require("node:path");

function resolveReviewSidecarPaths(resourcesPath) {
  const root = path.join(resourcesPath, "review-sidecar");
  return {
    python: path.join(root, "python", "bin", "python"),
    cwd: path.join(root, "app"),
  };
}

module.exports = { resolveReviewSidecarPaths };

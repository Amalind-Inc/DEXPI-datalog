const path = require('node:path');

function resolveReviewSidecarPaths({ isPackaged, resourcesPath, desktopDir }) {
  if (isPackaged) {
    const root = path.join(resourcesPath, 'review-sidecar');
    return { python: path.join(root, 'python', 'bin', 'python'), cwd: root };
  }
  return { python: path.resolve(desktopDir, '../../.venv/bin/python'), cwd: path.resolve(desktopDir, '../..') };
}

module.exports = { resolveReviewSidecarPaths };

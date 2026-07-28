import path from "node:path";

export interface ElectronResourcePathInput {
  isPackaged: boolean;
  resourcesPath: string;
  devRoot: string;
}

export function resolveReviewSidecarPaths(input: ElectronResourcePathInput): {
  python: string;
  cwd: string;
} {
  const root = input.isPackaged ? input.resourcesPath : input.devRoot;
  const sidecarRoot = path.join(root, "review-sidecar");
  return {
    python: path.join(sidecarRoot, "python", "bin", "python"),
    cwd: path.join(sidecarRoot, "app"),
  };
}

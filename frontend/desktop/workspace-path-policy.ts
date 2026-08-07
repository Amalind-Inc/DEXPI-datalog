import { createHash } from "node:crypto";
import { constants } from "node:fs";
import { lstat, open, realpath } from "node:fs/promises";
import { isAbsolute, relative, resolve } from "node:path";

const MAX_IGNORE_BYTES = 64 * 1024;
const MAX_POLICY_PATH_BYTES = 512;
const MAX_POLICY_PATH_DEPTH = 32;
const POLICY_VERSION = 1;
const DEFAULT_IGNORED_SEGMENTS: Record<string, true> = {
  ".cache": true,
  ".next": true,
  build: true,
  cache: true,
  coverage: true,
  dist: true,
  node_modules: true,
  out: true,
};
const POLICY_DIGEST_INPUT = JSON.stringify({
  schemaVersion: POLICY_VERSION,
  protected:
    ".env*,.git,.git-credentials,.ssh,.aws,.azure,.docker,.kube,.netrc,.npmrc,.pypirc,.portlog,.portlog-artifacts,credential*,secret*,id_rsa,id_dsa,id_ecdsa,id_ed25519,*.pem,*.key,*.p12,*.pfx",
  defaultIgnored: Object.keys(DEFAULT_IGNORED_SEGMENTS).sort(),
  ignoreSyntax: "comments,root-or-segment-globs,*,**,?,directory-suffix;no-negation",
  symlinks: "excluded",
});

export const PORTLOG_WORKSPACE_PATH_POLICY_DIGEST = `sha256:${createHash("sha256")
  .update(POLICY_DIGEST_INPUT)
  .digest("hex")}`;
export const PORTLOG_ABSENT_IGNORE_DIGEST = `sha256:${createHash("sha256")
  .update("portlogignore:absent")
  .digest("hex")}`;

export type WorkspacePathKind = "file" | "directory";
export type WorkspacePathDecision =
  | { include: true }
  | { include: false; reason: "protected" | "default_ignored" | "ignored" };

export interface PortLogWorkspacePathPolicy {
  readonly schemaVersion: 1;
  readonly policyDigest: string;
  readonly ignoreDigest: string;
  readonly ignorePresent: boolean;
  evaluate(relativePath: string, kind: WorkspacePathKind): WorkspacePathDecision;
}

type CompiledIgnorePattern = {
  readonly expression: RegExp;
  readonly directoryOnly: boolean;
};

export async function loadPortLogWorkspacePathPolicy(
  workspaceRoot: string,
): Promise<PortLogWorkspacePathPolicy> {
  const root = await realpath(workspaceRoot);
  const ignorePath = resolve(root, ".portlogignore");
  const ignore = await readStableIgnoreFile(ignorePath);
  const patterns = ignore ? compileIgnorePatterns(ignore.bytes.toString("utf8")) : [];

  return {
    schemaVersion: POLICY_VERSION,
    policyDigest: PORTLOG_WORKSPACE_PATH_POLICY_DIGEST,
    ignoreDigest: ignore?.digest ?? PORTLOG_ABSENT_IGNORE_DIGEST,
    ignorePresent: ignore !== undefined,
    evaluate(relativePath, kind) {
      const normalized = normalizeWorkspaceRelativePath(relativePath);
      if (normalized === ".portlogignore") return { include: true };
      if (isPortLogProtectedPath(normalized)) return { include: false, reason: "protected" };
      if (
        normalized
          .split("/")
          .some((segment) => DEFAULT_IGNORED_SEGMENTS[segment.toLowerCase()] === true)
      )
        return { include: false, reason: "default_ignored" };
      if (patterns.some((pattern) => matchesIgnorePattern(pattern, normalized, kind)))
        return { include: false, reason: "ignored" };
      return { include: true };
    },
  };
}

export function normalizeWorkspaceRelativePath(value: string): string {
  if (typeof value !== "string" || value.includes("\0") || value.includes("\\"))
    throw new Error("Workspace path is malformed.");
  const withoutPrefix = value.startsWith("./") ? value.slice(2) : value;
  if (!withoutPrefix || withoutPrefix.startsWith("/") || isAbsolute(withoutPrefix))
    throw new Error("Workspace path must be relative.");
  const segments = withoutPrefix.split("/");
  if (
    segments.some((segment) => !segment || segment === "." || segment === "..") ||
    segments.length > MAX_POLICY_PATH_DEPTH ||
    Buffer.byteLength(withoutPrefix, "utf8") > MAX_POLICY_PATH_BYTES
  )
    throw new Error("Workspace path exceeds the bounded path policy.");
  return segments.join("/");
}

export function isPortLogProtectedPath(relativePath: string): boolean {
  const normalized = normalizeWorkspaceRelativePath(relativePath);
  return normalized.split("/").some((segment) => {
    const name = segment.toLowerCase();
    return (
      name === ".git" ||
      name === ".git-credentials" ||
      name === ".ssh" ||
      name === ".aws" ||
      name === ".azure" ||
      name === ".docker" ||
      name === ".kube" ||
      name === ".netrc" ||
      name === ".npmrc" ||
      name === ".pypirc" ||
      name === ".portlog" ||
      name === ".portlog-artifacts" ||
      name.startsWith(".env") ||
      name.startsWith("credential") ||
      name.startsWith("secret") ||
      /^id_(?:rsa|dsa|ecdsa|ed25519)$/u.test(name) ||
      /\.(?:pem|key|p12|pfx)$/u.test(name)
    );
  });
}

export async function assertNoWorkspaceSymlinkComponents(
  workspaceRoot: string,
  candidate: string,
): Promise<{ root: string; path: string; relativePath: string }> {
  return assertWorkspacePathComponents(workspaceRoot, candidate, { allowMissingLeaf: false });
}

export async function assertWritableWorkspacePath(
  workspaceRoot: string,
  candidate: string,
): Promise<{ root: string; path: string; relativePath: string }> {
  return assertWorkspacePathComponents(workspaceRoot, candidate, { allowMissingSuffix: true });
}

async function assertWorkspacePathComponents(
  workspaceRoot: string,
  candidate: string,
  options: { allowMissingLeaf?: boolean; allowMissingSuffix?: boolean },
): Promise<{ root: string; path: string; relativePath: string }> {
  const root = await realpath(workspaceRoot);
  const lexicalRoot = resolve(workspaceRoot);
  const absoluteCandidate = resolve(lexicalRoot, candidate);
  const canonicalCandidate = isWithinWorkspace(lexicalRoot, absoluteCandidate)
    ? relative(lexicalRoot, absoluteCandidate)
    : candidate;
  const lexicalPath = resolve(root, canonicalCandidate);
  if (!isWithinWorkspace(root, lexicalPath))
    throw new Error("Workspace path escapes the authorized workspace.");
  const relativePath = relative(root, lexicalPath).split("\\").join("/");
  if (!relativePath) return { root, path: root, relativePath: "" };
  const normalized = normalizeWorkspaceRelativePath(relativePath);
  const segments = normalized.split("/");
  let current = root;
  for (let index = 0; index < segments.length; index += 1) {
    current = resolve(current, segments[index]!);
    try {
      const status = await lstat(current);
      if (status.isSymbolicLink()) throw new Error("Workspace path contains a symbolic link.");
    } catch (error) {
      const missing = isNodeError(error) && error.code === "ENOENT";
      if (
        missing &&
        (options.allowMissingSuffix || (options.allowMissingLeaf && index === segments.length - 1))
      )
        return { root, path: lexicalPath, relativePath: normalized };
      throw error instanceof Error ? error : new Error("Workspace path is unavailable.");
    }
  }
  return { root, path: lexicalPath, relativePath: normalized };
}

export function isWithinWorkspace(workspaceRoot: string, candidate: string): boolean {
  const suffix = relative(workspaceRoot, candidate);
  return (
    suffix === "" ||
    (suffix !== ".." &&
      !suffix.startsWith(`..${process.platform === "win32" ? "\\" : "/"}`) &&
      !isAbsolute(suffix))
  );
}

async function readStableIgnoreFile(
  ignorePath: string,
): Promise<{ bytes: Buffer; digest: string } | undefined> {
  let handle;
  try {
    handle = await open(ignorePath, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
  } catch (error) {
    if (isNodeError(error) && error.code === "ENOENT") return undefined;
    throw new Error("The PortLog ignore policy could not be opened safely.");
  }
  try {
    const before = await handle.stat();
    if (!before.isFile() || before.nlink !== 1)
      throw new Error("The PortLog ignore policy must be a single-link regular file.");
    if (before.size > MAX_IGNORE_BYTES) throw new Error("The PortLog ignore policy is too large.");
    const bytes = await handle.readFile();
    const after = await handle.stat();
    if (
      bytes.byteLength !== before.size ||
      after.size !== before.size ||
      after.dev !== before.dev ||
      after.ino !== before.ino ||
      after.mtimeMs !== before.mtimeMs ||
      after.nlink !== 1
    )
      throw new Error("The PortLog ignore policy changed while it was read.");
    return {
      bytes,
      digest: `sha256:${createHash("sha256").update(bytes).digest("hex")}`,
    };
  } finally {
    await handle.close();
  }
}

function compileIgnorePatterns(source: string): CompiledIgnorePattern[] {
  const patterns: CompiledIgnorePattern[] = [];
  for (const rawLine of source.split(/\r?\n/u)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    if (line.startsWith("!") || line.includes("\\") || line.includes("\0"))
      throw new Error("The PortLog ignore policy uses unsupported syntax.");
    const directoryOnly = line.endsWith("/");
    const unwrapped = (directoryOnly ? line.slice(0, -1) : line).replace(/^\//u, "");
    if (
      !unwrapped ||
      unwrapped.split("/").some((segment) => !segment || segment === "." || segment === "..") ||
      Buffer.byteLength(unwrapped, "utf8") > MAX_POLICY_PATH_BYTES
    )
      throw new Error("The PortLog ignore policy contains an invalid pattern.");
    const pathAware = unwrapped.includes("/");
    const expression = globExpression(unwrapped);
    patterns.push({
      expression: new RegExp(
        pathAware ? `^${expression}(?:/|$)` : `(?:^|/)${expression}(?:/|$)`,
        "u",
      ),
      directoryOnly,
    });
  }
  return patterns;
}

function globExpression(pattern: string): string {
  let expression = "";
  for (let index = 0; index < pattern.length; index += 1) {
    const character = pattern[index];
    if (character === "*") {
      if (pattern[index + 1] === "*") {
        expression += ".*";
        index += 1;
      } else expression += "[^/]*";
    } else if (character === "?") expression += "[^/]";
    else expression += character.replace(/[|\\{}()[\]^$+?.]/gu, "\\$&");
  }
  return expression;
}

function matchesIgnorePattern(
  pattern: CompiledIgnorePattern,
  relativePath: string,
  kind: WorkspacePathKind,
): boolean {
  if (pattern.directoryOnly && kind !== "directory" && !pattern.expression.test(relativePath))
    return false;
  return pattern.expression.test(relativePath);
}

function isNodeError(error: unknown): error is NodeJS.ErrnoException {
  return error instanceof Error && "code" in error;
}

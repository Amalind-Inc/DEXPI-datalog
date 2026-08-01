import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptRoot = path.dirname(fileURLToPath(import.meta.url));
const targetRoot = path.resolve(process.argv[2] ?? path.join(scriptRoot, "..", "frontend"));
const oauthPage = path.join(
  targetRoot,
  "node_modules",
  "@earendil-works",
  "pi-ai",
  "dist",
  "utils",
  "oauth",
  "oauth-page.js",
);
const source = await readFile(oauthPage, "utf8");

const logo = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 280 72" role="img" aria-label="PortLog"><text x="0" y="51" fill="#fafafa" font-family="ui-monospace, SFMono-Regular, Menlo, monospace" font-size="42" font-weight="700" letter-spacing="5">PORTLOG</text></svg>`;
const branded = source
  .replace(/const LOGO_SVG = `[^`]*`;/s, `const LOGO_SVG = \`${logo}\`;`)
  .replace('title: "Authentication successful"', 'title: "PortLog authorization complete"')
  .replace('heading: "Authentication successful"', 'heading: "PortLog is connected"')
  .replace('title: "Authentication failed"', 'title: "PortLog authorization failed"')
  .replace('heading: "Authentication failed"', 'heading: "PortLog could not connect"')
  .replace(
    "    .logo {\n      width: 72px;\n      height: 72px;",
    "    .logo {\n      width: 176px;\n      height: 45px;",
  );
if (!branded.includes("PortLog authorization complete"))
  throw new Error(`Could not apply the PortLog OAuth callback patch to ${oauthPage}`);
if (branded === source) {
  console.log(`OAuth callback branding already applied: ${oauthPage}`);
} else {
  await writeFile(oauthPage, branded);
  console.log(`Applied PortLog OAuth callback branding: ${oauthPage}`);
}

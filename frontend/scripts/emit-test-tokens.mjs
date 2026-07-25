/**
 * Emits real Better Auth JWTs and the matching JWKS, for verifying the
 * cross-language boundary.
 *
 * The Python backend trusts a token only if it verifies against the JWKS this
 * app publishes. That contract spans two languages and two crypto libraries,
 * so it is checked with genuine artifacts rather than assumed: this script
 * signs two users up and writes their tokens plus the JWKS to a directory that
 * `tests/web/test_better_auth_contract.py` reads.
 *
 * Usage: node scripts/emit-test-tokens.mjs <output-dir>
 */

import Database from "better-sqlite3";
import { betterAuth } from "better-auth";
import { getMigrations } from "better-auth/db/migration";
import { jwt } from "better-auth/plugins";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";

const outputDir = resolve(process.argv[2] ?? "./.tmp/auth-contract");
const baseURL = "http://localhost:3000";

mkdirSync(outputDir, { recursive: true });
const databasePath = join(outputDir, "auth.sqlite3");
rmSync(databasePath, { force: true });

const auth = betterAuth({
  database: new Database(databasePath),
  baseURL,
  secret: "contract-probe-secret-0123456789abcdef",
  emailAndPassword: { enabled: true },
  plugins: [jwt()],
});

// A fresh database each run, so the artifacts never depend on earlier state.
const { runMigrations } = await getMigrations(auth.options);
await runMigrations();

async function tokenFor(email) {
  const signUp = await auth.api.signUpEmail({
    body: { email, password: "correct-horse-battery-staple", name: email },
    returnHeaders: true,
  });
  const setCookie = signUp.headers?.get("set-cookie");
  if (!setCookie) throw new Error(`no session cookie for ${email}`);
  const cookie = setCookie
    .split(",")
    .map((part) => part.trim().split(";")[0])
    .join("; ");
  const token = await auth.api.getToken({
    headers: new Headers({ cookie }),
  });
  return { email, userId: signUp.response?.user?.id, token: token.token };
}

const users = [await tokenFor("alice@example.com"), await tokenFor("bob@example.com")];
const jwks = await auth.api.getJwks();

writeFileSync(
  join(outputDir, "tokens.json"),
  JSON.stringify({ baseURL, users, jwks }, null, 2),
  "utf-8",
);
console.log(`wrote ${join(outputDir, "tokens.json")}`);
for (const user of users) {
  console.log(`  ${user.email} -> ${user.token.slice(0, 24)}...`);
}
console.log(`  jwks keys: ${jwks.keys.map((k) => k.alg ?? k.kty).join(", ")}`);

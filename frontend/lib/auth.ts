/**
 * Sign-in for the hosted deployment profile (ADR 0016).
 *
 * Better Auth is the issuer; the Python backend is a resource server that
 * verifies the JWT against the JWKS this exposes at `/api/auth/jwks`. That is
 * a standard OAuth2 split rather than auth logic living in two places: nothing
 * here decides what a signed-in user may do, only who they are.
 *
 * Nothing is constructed at module scope, and that is load-bearing rather than
 * stylistic. `betterAuth` opens a SQLite database eagerly, and better-sqlite3
 * creates the file on open, so a module-level instance meant a local install
 * grew an empty accounts database the moment Next evaluated the auth route.
 * ADR 0016 says the local profile has no accounts; a stray `auth.sqlite3` on a
 * single operator's disk makes that untrue. Callers use `getAuth()`, and the
 * local profile never calls it.
 */

import Database from "better-sqlite3";
import { betterAuth } from "better-auth";
import { jwt } from "better-auth/plugins";
import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";

import { configuredSocialProviders } from "./social-providers.ts";

/**
 * Where the account database lives. SQLite today; ADR 0016 puts the hosted
 * catalog on libSQL, which shares the dialect, so this becomes one connection
 * string change rather than a migration rewrite (bead 2afe.7).
 */
function authDatabasePath(): string {
  const configured = process.env.PYDEXPI_AUTH_DB?.trim();
  const path = resolve(
    process.cwd(),
    configured && configured !== "" ? configured : "../.tmp/auth.sqlite3",
  );
  mkdirSync(dirname(path), { recursive: true });
  return path;
}

function baseUrl(): string {
  return process.env.BETTER_AUTH_URL?.trim() || "http://localhost:3000";
}

/**
 * Refuse to run a hosted instance on a guessable signing secret. Locally a
 * fixed development secret is fine and keeps `npm run dev` working: the local
 * profile issues no tokens the backend will honour anyway.
 */
function authSecret(): string {
  const configured = process.env.BETTER_AUTH_SECRET?.trim();
  if (configured) return configured;
  if (process.env.PYDEXPI_DEPLOYMENT_PROFILE?.trim().toLowerCase() === "hosted") {
    throw new Error(
      "BETTER_AUTH_SECRET is not set. A hosted deployment signs session " +
        "cookies with it, so starting on a default would let anyone forge a " +
        "session. Generate one with: openssl rand -base64 32",
    );
  }
  return "development-only-secret-not-for-hosted-use";
}

function createHostedAuth() {
  return betterAuth({
    database: new Database(authDatabasePath()),
    baseURL: baseUrl(),
    secret: authSecret(),
    // Email and password is always on: it needs no external service, so a
    // self-hoster can run the hosted profile without signing up for anything.
    // Social providers sit alongside it rather than replacing it, and are
    // configuration -- `social-providers.ts` decides which, from the
    // environment, and the sign-in page reads the same decision so a button
    // can never point at a provider this instance did not configure.
    emailAndPassword: { enabled: true },
    socialProviders: configuredSocialProviders(process.env),
    plugins: [jwt()],
  });
}

/**
 * The auth instance's type, named here so consumers import a name rather than
 * restating an inference.
 *
 * Better Auth's `Auth<Options>` is generic over the exact options object -- the
 * plugin list shapes `api`, so `Auth<BetterAuthOptions>` does not typecheck and
 * the concrete instantiation cannot be hand-written. Deriving it once, at the
 * module that owns the value, is the closest thing to a concrete exported type.
 */
export type HostedAuth = ReturnType<typeof createHostedAuth>;

let cached: HostedAuth | null = null;

/** The auth instance, built on first use. Hosted profile only. */
export function getAuth(): HostedAuth {
  cached ??= createHostedAuth();
  return cached;
}

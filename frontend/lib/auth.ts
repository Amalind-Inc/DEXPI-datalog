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

import {
  type SmtpSettings,
  resetPasswordMessage,
  smtpSettings,
  verifyEmailMessage,
} from "./email.ts";
import { configuredSocialProviders } from "./social-providers.ts";

/**
 * Where the account database lives. SQLite today; ADR 0016 puts the hosted
 * catalog on libSQL, which shares the dialect, so this becomes one connection
 * string change rather than a migration rewrite (bead 2afe.7).
 */
function authDatabasePath(): string {
  const configured = process.env.HARBORFIELD_AUTH_DB?.trim();
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
  if (process.env.HARBORFIELD_DEPLOYMENT_PROFILE?.trim().toLowerCase() === "hosted") {
    throw new Error(
      "BETTER_AUTH_SECRET is not set. A hosted deployment signs session " +
        "cookies with it, so starting on a default would let anyone forge a " +
        "session. Generate one with: openssl rand -base64 32",
    );
  }
  return "development-only-secret-not-for-hosted-use";
}

/**
 * Send one message, over SMTP, or throw.
 *
 * Better Auth treats a rejected `sendResetPassword` as a failed request, which
 * is the behaviour worth having: a reset that silently fails to send looks
 * identical to one that worked, and the person waits for mail that will never
 * arrive.
 *
 * `nodemailer` is imported lazily for the same reason nothing here is built at
 * module scope -- a local install should not pay for a transport it never uses.
 */
async function sendMail(
  settings: SmtpSettings,
  to: string,
  message: { subject: string; text: string; html: string },
): Promise<void> {
  const { createTransport } = await import("nodemailer");
  const transport = createTransport({
    host: settings.host,
    port: settings.port,
    secure: settings.secure,
    ...(settings.auth ? { auth: settings.auth } : {}),
  });
  await transport.sendMail({ from: settings.from, to, ...message });
}

function createHostedAuth() {
  // Read once, at construction: a deployment does not grow an SMTP server
  // between requests, and reading per-send would turn a configuration error
  // into an intermittent one.
  const smtp = smtpSettings(process.env);

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
    emailAndPassword: {
      enabled: true,
      // Better Auth owns the reset entirely -- token, expiry, single use, and
      // the exchange. The only thing it cannot supply is a way to deliver the
      // link, so without SMTP the endpoint stays off rather than half-working.
      ...(smtp
        ? {
            sendResetPassword: async ({ user, url }: { user: { email: string }; url: string }) => {
              await sendMail(smtp, user.email, resetPasswordMessage(url));
            },
            // Enforcement and delivery move together, and the reason is in
            // Better Auth's sign-in path: when this is true and
            // `sendVerificationEmail` is missing it throws EMAIL_NOT_VERIFIED
            // with no route to a token, so every account is locked out for
            // good. Requiring verification is therefore only safe in the same
            // branch that can actually send the link.
            requireEmailVerification: true,
          }
        : {}),
    },
    ...(smtp
      ? {
          emailVerification: {
            sendVerificationEmail: async ({
              user,
              url,
            }: {
              user: { email: string };
              url: string;
            }) => {
              await sendMail(smtp, user.email, verifyEmailMessage(url));
            },
            sendOnSignUp: true,
            // A blocked sign-in resends rather than dead-ending. Without this
            // someone who lost the first message has no way to ask for another
            // and simply cannot get in.
            sendOnSignIn: true,
            // Following the link is proof enough; making them type the
            // password again buys nothing.
            autoSignInAfterVerification: true,
          },
        }
      : {}),
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

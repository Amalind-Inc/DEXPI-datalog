/**
 * Outbound email for the hosted profile: SMTP settings, or nothing.
 *
 * This exists because Better Auth implements password reset completely --
 * endpoint, token, expiry, exchange -- and declines to run it without a way
 * to send the message. The missing piece was never auth. It was a mailer.
 *
 * SMTP rather than a vendor API on purpose. A self-hoster already has a relay,
 * or can run one; requiring a Resend or SendGrid account would put a signup
 * between someone and a working password reset, which is the same barrier that
 * offering email-and-password sign-in exists to avoid.
 *
 * Like `social-providers.ts`, this is a pure map from environment to intent,
 * with no transport import, so the decision can be tested without a server.
 */

/** Every variable this module reads. The README table is generated from it. */
export const SMTP_VARS = [
  "SMTP_HOST",
  "SMTP_PORT",
  "SMTP_FROM",
  "SMTP_USER",
  "SMTP_PASSWORD",
  "SMTP_SECURE",
] as const;

export type SmtpAuth = { user: string; pass: string };

export type SmtpSettings = {
  host: string;
  port: number;
  from: string;
  /** Implicit TLS on connect, as opposed to STARTTLS after it. */
  secure: boolean;
  auth: SmtpAuth | null;
};

type Env = Record<string, string | undefined>;

function read(env: Env, name: string): string {
  return env[name]?.trim() ?? "";
}

function refuse(missing: string, present: string): never {
  throw new Error(
    `${present} is set but ${missing} is not, so password reset email cannot ` +
      `be sent. Set every one of SMTP_HOST, SMTP_PORT and SMTP_FROM to enable ` +
      `it, or none of them to leave sign-in as email and password only.`,
  );
}

/**
 * The submission port. 25 is the wrong default for an application: it is the
 * relay port, usually blocked, and picking it silently would produce a hang.
 */
const DEFAULT_PORT = 587;

function port(env: Env): number {
  const raw = read(env, "SMTP_PORT");
  if (raw === "") return DEFAULT_PORT;

  const value = Number(raw);
  // `Number("")` is 0 and `Number("587x")` is NaN. Both would otherwise reach
  // the socket layer as a failure a long way from the typo that caused it.
  if (!Number.isInteger(value) || value < 1 || value > 65535) {
    throw new Error(
      `SMTP_PORT must be a port number between 1 and 65535, got ${JSON.stringify(raw)}.`,
    );
  }
  return value;
}

/**
 * SMTP settings, or `null` when this deployment sends no mail.
 *
 * Throws when the configuration is partial. Setting `SMTP_HOST` alone is an
 * unambiguous request for email, and the failure that helps names the variable
 * still missing rather than hiding the feature.
 */
export function smtpSettings(env: Env): SmtpSettings | null {
  const host = read(env, "SMTP_HOST");
  const from = read(env, "SMTP_FROM");
  const rawPort = read(env, "SMTP_PORT");

  if (host === "" && from === "" && rawPort === "") return null;

  if (host === "") refuse("SMTP_HOST", from !== "" ? "SMTP_FROM" : "SMTP_PORT");
  if (from === "") refuse("SMTP_FROM", "SMTP_HOST");

  const user = read(env, "SMTP_USER");
  const pass = read(env, "SMTP_PASSWORD");
  // A password with no username would be sent as an anonymous connection, so
  // the credential would be silently unused rather than rejected.
  if (pass !== "" && user === "") refuse("SMTP_USER", "SMTP_PASSWORD");
  if (user !== "" && pass === "") refuse("SMTP_PASSWORD", "SMTP_USER");

  const resolvedPort = port(env);
  const secureFlag = read(env, "SMTP_SECURE").toLowerCase();

  return {
    host,
    from,
    port: resolvedPort,
    // 465 is implicit TLS by convention; everything else negotiates STARTTLS.
    secure: secureFlag === "true" || secureFlag === "1" || resolvedPort === 465,
    // Relays on a private network commonly accept unauthenticated mail, so an
    // absent credential is a valid configuration rather than an omission.
    auth: user !== "" && pass !== "" ? { user, pass } : null,
  };
}

/** Whether the sign-in page should offer a reset link. */
export function isEmailConfigured(env: Env): boolean {
  return smtpSettings(env) !== null;
}

/**
 * The reset message. Kept here, beside the settings, so the wording is
 * reviewable without reading the auth wiring.
 */
export function resetPasswordMessage(url: string): {
  subject: string;
  text: string;
  html: string;
} {
  const subject = "Reset your DEXPI-datalog password";
  const text = [
    "Someone asked to reset the password for this DEXPI-datalog account.",
    "",
    "Open this link to choose a new one:",
    url,
    "",
    "The link expires in an hour and can be used once.",
    "If you didn't request this, you can ignore this message: your password",
    "will not change until the link is used.",
  ].join("\n");
  const html = [
    "<p>Someone asked to reset the password for this DEXPI-datalog account.</p>",
    `<p><a href="${url}">Choose a new password</a></p>`,
    "<p>The link expires in an hour and can be used once.</p>",
    "<p>If you didn't request this, you can ignore this message: your password",
    " will not change until the link is used.</p>",
  ].join("");

  return { subject, text, html };
}

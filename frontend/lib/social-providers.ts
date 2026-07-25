/**
 * Which social sign-in providers this deployment offers (hosted profile only).
 *
 * Better Auth ships Apple and Google as built-in providers, so offering them
 * is configuration rather than code -- but only if a provider that nobody
 * configured stays invisible. A button that reaches an unconfigured provider
 * fails at the redirect, off in Google's error page, where the operator has
 * nothing to search for. So one function decides, from the environment alone,
 * and both callers read it: `auth.ts` builds `socialProviders` from it, and
 * the sign-in page renders buttons from it. They cannot disagree.
 *
 * This module holds no Better Auth import on purpose. It is a pure map from
 * environment to intent, which is what makes it testable without opening a
 * database or standing up a provider.
 */

export type SocialProviderId = "google" | "apple";

/** A provider's credential pair, in the shape Better Auth expects. */
export type SocialProviderCredentials = {
  clientId: string;
  clientSecret: string;
};

/** What the browser is allowed to know: an id and something to put on a button. */
export type OfferedSocialProvider = {
  id: SocialProviderId;
  label: string;
};

type SocialProviderDefinition = OfferedSocialProvider & {
  envPrefix: string;
  idVar: string;
  secretVar: string;
};

/**
 * The providers this codebase knows how to offer, in the order they appear on
 * the sign-in page. Order lives here rather than at the call site so that two
 * deployments setting their variables in different orders still render the
 * same page.
 */
export const SOCIAL_PROVIDERS: readonly SocialProviderDefinition[] = [
  {
    id: "google",
    label: "Continue with Google",
    envPrefix: "GOOGLE_",
    idVar: "GOOGLE_CLIENT_ID",
    secretVar: "GOOGLE_CLIENT_SECRET",
  },
  {
    id: "apple",
    label: "Continue with Apple",
    envPrefix: "APPLE_",
    idVar: "APPLE_CLIENT_ID",
    secretVar: "APPLE_CLIENT_SECRET",
  },
];

type Env = Record<string, string | undefined>;

/**
 * Trailing newlines arrive with copied secrets, and an empty string arrives
 * from a compose file that declares a variable without giving it a value.
 * Neither is configuration.
 */
function read(env: Env, name: string): string {
  return env[name]?.trim() ?? "";
}

/**
 * Refuse a half-configured provider instead of quietly dropping it.
 *
 * Setting one variable of a pair is an unambiguous statement of intent, so
 * the failure that helps is the one that names the variable still missing --
 * the same shape as `authSecret()` and the Python profile loaders.
 */
function requireBothOrNeither(
  provider: SocialProviderDefinition,
  clientId: string,
  clientSecret: string,
): void {
  if (clientId !== "" && clientSecret !== "") return;
  if (clientId === "" && clientSecret === "") return;

  const missing = clientId === "" ? provider.idVar : provider.secretVar;
  const present = clientId === "" ? provider.secretVar : provider.idVar;
  throw new Error(
    `${present} is set but ${missing} is not, so ${provider.label} cannot be ` +
      `offered. Set both to enable it, or neither to leave it off. Sign-in ` +
      `with an email address keeps working either way.`,
  );
}

/**
 * The credential pairs to hand Better Auth. Empty when nothing is configured,
 * which is the ordinary case for a self-hosted install.
 */
export function configuredSocialProviders(
  env: Env,
): Partial<Record<SocialProviderId, SocialProviderCredentials>> {
  const configured: Partial<Record<SocialProviderId, SocialProviderCredentials>> = {};

  for (const provider of SOCIAL_PROVIDERS) {
    const clientId = read(env, provider.idVar);
    const clientSecret = read(env, provider.secretVar);
    requireBothOrNeither(provider, clientId, clientSecret);
    if (clientId === "" || clientSecret === "") continue;
    configured[provider.id] = { clientId, clientSecret };
  }

  return configured;
}

/**
 * The same decision, reduced to what a page may render. Returning a new object
 * per provider rather than the definition keeps `envPrefix` and the variable
 * names -- and any field added to the table later -- out of the HTML.
 */
export function enabledSocialProviders(env: Env): OfferedSocialProvider[] {
  const configured = configuredSocialProviders(env);
  return SOCIAL_PROVIDERS.filter((provider) => configured[provider.id] !== undefined).map(
    (provider) => ({ id: provider.id, label: provider.label }),
  );
}

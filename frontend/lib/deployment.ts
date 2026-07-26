/**
 * Which deployment profile this frontend is serving (ADR 0016).
 *
 * The Python backend refuses to start without an explicit profile. This side
 * defaults to `local` instead, and the asymmetry is deliberate: the backend is
 * where the profile is *enforced*, and it already rejects every unauthenticated
 * request in the hosted profile. All this setting decides here is whether to
 * render a sign-in surface. A hosted frontend that lost the variable would show
 * no sign-in and every call would 401 -- broken and obvious, not insecure --
 * whereas failing the boot would break `npm run dev` for every local user to
 * guard something the backend already guards.
 */

export type DeploymentProfile = "local" | "hosted";

export const PROFILE_ENV_VAR = "HARBORFIELD_DEPLOYMENT_PROFILE";

export function deploymentProfile(env: NodeJS.ProcessEnv = process.env): DeploymentProfile {
  return env[PROFILE_ENV_VAR]?.trim().toLowerCase() === "hosted" ? "hosted" : "local";
}

export function isHostedProfile(env: NodeJS.ProcessEnv = process.env): boolean {
  return deploymentProfile(env) === "hosted";
}

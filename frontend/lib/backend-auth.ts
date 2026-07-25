/**
 * The one place a caller's identity is attached to a backend request.
 *
 * Every function in `review-backend.ts` already accepted an injectable
 * `fetcher`, defaulting to `fetch`. Changing that default is the whole
 * integration: identity is added in one place rather than at ~25 call sites,
 * so a new endpoint cannot forget it.
 *
 * Fails closed. If no token can be produced the request goes out
 * unauthenticated and the backend refuses it in the hosted profile -- an
 * error, but never a request quietly attributed to the wrong user.
 */

import { isHostedProfile } from "./deployment.ts";

/**
 * The signed-in caller's JWT, or null.
 *
 * Null is the ordinary answer in three cases: the local profile, which has no
 * accounts; a signed-out visitor; and any non-Next context such as the unit
 * tests, which import this module without a request to read.
 */
async function hostedBearerToken(): Promise<string | null> {
  if (!isHostedProfile()) return null;
  // Dynamic import, deliberately. Static imports cannot work here for two
  // concrete reasons, not for style:
  //   `next/headers` does not resolve outside Next. `review-backend.ts`
  //   imports this module and is exercised by `node:test` unit tests under
  //   plain node, where a static import would fail at load.
  //   `./auth` constructs a better-sqlite3 Database at module scope. Importing
  //   it statically would create an accounts database in the local profile,
  //   which by ADR 0016 has no accounts at all.
  try {
    const { headers } = await import("next/headers");
    const { getAuth } = await import("./auth");
    const result = await getAuth().api.getToken({ headers: await headers() });
    return result?.token ?? null;
  } catch {
    // No session, or no request context. Both mean "not signed in" as far as
    // the backend is concerned, and the backend is what enforces that.
    return null;
  }
}

export const backendFetch: typeof fetch = async (input, init) => {
  const token = await hostedBearerToken();
  if (!token) return fetch(input, init);
  const merged = new Headers(init?.headers);
  merged.set("Authorization", `Bearer ${token}`);
  return fetch(input, { ...init, headers: merged });
};

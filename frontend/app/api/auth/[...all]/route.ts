import { toNextJsHandler } from "better-auth/next-js";

import { getAuth } from "@/lib/auth";
import { isHostedProfile } from "@/lib/deployment";

/**
 * Sign-in, sign-out, session, and the JWKS the Python backend verifies
 * against.
 *
 * In the local profile these endpoints do not exist. That is stronger than not
 * linking to them: ADR 0016 says the local profile has no sign-in surface, and
 * a route that answers is a surface whether or not anything points at it.
 * Returning 404 before touching `getAuth()` also keeps a local install from
 * ever opening an accounts database.
 */

let handlers: ReturnType<typeof toNextJsHandler> | null = null;

function hostedHandlers() {
  handlers ??= toNextJsHandler(getAuth());
  return handlers;
}

const notFound = () => new Response(null, { status: 404 });

export async function GET(request: Request): Promise<Response> {
  if (!isHostedProfile()) return notFound();
  return hostedHandlers().GET(request);
}

export async function POST(request: Request): Promise<Response> {
  if (!isHostedProfile()) return notFound();
  return hostedHandlers().POST(request);
}

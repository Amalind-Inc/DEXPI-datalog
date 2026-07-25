/**
 * The sign-in route, as a server component.
 *
 * Its only job is to decide which social providers this deployment offers and
 * hand that list to the form. Reading it here rather than in the browser is
 * what keeps `GOOGLE_CLIENT_SECRET` out of the bundle: only the provider ids
 * and their button labels cross to the client, which
 * `social-providers.test.ts` asserts by serialising the value.
 *
 * `enabledSocialProviders` throws when a credential pair is half set. That
 * surfaces here as a failed render rather than a button that redirects into a
 * provider error page, which is the trade this codebase makes everywhere
 * else: fail where the misconfiguration is, naming it.
 */

import { enabledSocialProviders } from "@/lib/social-providers.ts";

import SignInForm from "./sign-in-form.tsx";

export default function SignInPage() {
  return <SignInForm socialProviders={enabledSocialProviders(process.env)} />;
}

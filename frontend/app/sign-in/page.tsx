/**
 * The sign-in route, as a server component.
 *
 * Its only job is to decide what this deployment can actually offer -- which
 * social providers, and whether a password reset can be delivered -- and hand
 * that to the form. Reading it here rather than in the browser keeps
 * `GOOGLE_CLIENT_SECRET` and `SMTP_PASSWORD` out of the bundle: only booleans
 * and button labels cross to the client.
 *
 * Both readers throw on half-configuration, which surfaces here as a failed
 * render rather than a control that quietly does nothing. That is the trade
 * this codebase makes everywhere else: fail where the misconfiguration is,
 * naming it.
 */

import { isEmailConfigured } from "@/lib/email.ts";
import { enabledSocialProviders } from "@/lib/social-providers.ts";

import SignInForm from "./sign-in-form.tsx";

export default async function SignInPage({
  searchParams,
}: {
  searchParams: Promise<{ mode?: string }>;
}) {
  const { mode } = await searchParams;
  return (
    <SignInForm
      socialProviders={enabledSocialProviders(process.env)}
      canResetPassword={isEmailConfigured(process.env)}
      // Same source of truth: addresses are verified exactly when mail can be
      // sent, because requiring it without a sender locks every account out.
      verifiesEmail={isEmailConfigured(process.env)}
      initialMode={mode === "sign-up" ? "sign-up" : "sign-in"}
    />
  );
}

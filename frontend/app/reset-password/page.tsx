"use client";

/**
 * Where a password-reset link lands.
 *
 * The token arrives as a query parameter and is handed straight back to Better
 * Auth, which owns its validity, its expiry and its single use. Nothing here
 * inspects it -- a page that tried to decide whether a token looked valid
 * would be a second, worse implementation of a check that already exists.
 *
 * Reachable only when SMTP is configured, because nothing else sends a link
 * here, but it is not gated: a link that outlives a configuration change
 * should fail on the token, with a reason, rather than 404.
 */

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, type FormEvent, useState } from "react";

import { resetPassword } from "@/lib/auth-client";

function ResetPasswordForm() {
  const router = useRouter();
  const token = useSearchParams().get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    // Checked here rather than server-side because it is a typing mistake, not
    // a security property: the server has no second field to compare against.
    if (password !== confirmation) {
      setError("Those two passwords are different.");
      return;
    }

    setBusy(true);
    setError(null);
    const result = await resetPassword({ newPassword: password, token });
    setBusy(false);

    if (result.error) {
      setError(result.error.message ?? "That reset link did not work.");
      return;
    }
    // Better Auth invalidates other sessions on reset, so sign-in is the
    // honest next step rather than assuming this browser is now signed in.
    router.push("/sign-in");
    router.refresh();
  }

  if (token === "") {
    return (
      <main className="sign-in-page">
        <div className="sign-in-card">
          <h1 className="sign-in-title">This link is incomplete</h1>
          <p className="sign-in-subtitle">
            The address has no reset token in it. Mail clients sometimes break long links across
            lines -- copying the whole link into the address bar usually fixes it. Otherwise,
            request a new one.
          </p>
          <a className="sign-in-toggle" href="/sign-in">
            Back to sign in
          </a>
        </div>
      </main>
    );
  }

  return (
    <main className="sign-in-page">
      <form className="sign-in-card" onSubmit={submit}>
        <h1 className="sign-in-title">Choose a new password</h1>
        <p className="sign-in-subtitle">
          This link can be used once, and signs you out everywhere else.
        </p>

        <label className="sign-in-label" htmlFor="password">
          New password
        </label>
        <input
          id="password"
          className="sign-in-input"
          type="password"
          autoComplete="new-password"
          required
          minLength={8}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />

        <label className="sign-in-label" htmlFor="confirmation">
          New password again
        </label>
        <input
          id="confirmation"
          className="sign-in-input"
          type="password"
          autoComplete="new-password"
          required
          minLength={8}
          value={confirmation}
          onChange={(event) => setConfirmation(event.target.value)}
        />

        {error ? (
          <p className="sign-in-error" role="alert">
            {error}
          </p>
        ) : null}

        <button className="sign-in-submit" type="submit" disabled={busy}>
          {busy ? "Working..." : "Set new password"}
        </button>
      </form>
    </main>
  );
}

export default function ResetPasswordPage() {
  // `useSearchParams` suspends during prerender; without this the route fails
  // to build rather than failing at runtime.
  return (
    <Suspense fallback={<main className="sign-in-page" />}>
      <ResetPasswordForm />
    </Suspense>
  );
}

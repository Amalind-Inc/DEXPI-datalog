"use client";

/**
 * Sign in, or create an account, for the hosted profile.
 *
 * Email and password only. That is not a placeholder for social login: it is
 * the choice that lets someone run the hosted profile without signing up for
 * an external identity service, which matters for a repository that promises
 * a standalone story (ADR 0016).
 */

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { signIn, signUp } from "@/lib/auth-client";

type Mode = "sign-in" | "sign-up";

export default function SignInPage() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("sign-in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const result =
      mode === "sign-in"
        ? await signIn.email({ email, password })
        : await signUp.email({ email, password, name: email });
    setBusy(false);
    if (result.error) {
      // The provider's message is shown as-is rather than reworded: guessing
      // at a friendlier phrasing is how "wrong password" becomes "unknown
      // error" and the reviewer stops being able to fix their own problem.
      setError(result.error.message ?? "Could not sign in.");
      return;
    }
    router.push("/assistant");
    router.refresh();
  }

  return (
    <main className="sign-in-page">
      <form className="sign-in-card" onSubmit={submit}>
        <h1 className="sign-in-title">{mode === "sign-in" ? "Sign in" : "Create an account"}</h1>
        <p className="sign-in-subtitle">
          Your reviews, diagrams, and authored rule packs are private to your account.
        </p>

        <label className="sign-in-label" htmlFor="email">
          Email
        </label>
        <input
          id="email"
          className="sign-in-input"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />

        <label className="sign-in-label" htmlFor="password">
          Password
        </label>
        <input
          id="password"
          className="sign-in-input"
          type="password"
          autoComplete={mode === "sign-in" ? "current-password" : "new-password"}
          required
          minLength={8}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />

        {error ? (
          <p className="sign-in-error" role="alert">
            {error}
          </p>
        ) : null}

        <button className="sign-in-submit" type="submit" disabled={busy}>
          {busy ? "Working..." : mode === "sign-in" ? "Sign in" : "Create account"}
        </button>

        <button
          className="sign-in-toggle"
          type="button"
          onClick={() => {
            setMode(mode === "sign-in" ? "sign-up" : "sign-in");
            setError(null);
          }}
        >
          {mode === "sign-in" ? "No account yet? Create one" : "Already have an account? Sign in"}
        </button>
      </form>
    </main>
  );
}

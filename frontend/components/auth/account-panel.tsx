"use client";

/**
 * Who is signed in, and the way out.
 *
 * Renders nothing whatsoever in the local profile. ADR 0016 is explicit that
 * the local profile has no sign-in surface -- "not a stubbed login, genuinely
 * absent" -- so this is an early return before any auth hook runs, and the
 * local profile never even subscribes to a session.
 */

import Link from "next/link";
import { useRouter } from "next/navigation";

import { signOut, useSession } from "@/lib/auth-client";

export function AccountPanel({ hosted }: { hosted: boolean }) {
  // Deliberately before any hook: the hosted-only component below is what
  // holds the session subscription, so local renders no auth code at all.
  if (!hosted) return null;
  return <HostedAccountPanel />;
}

function HostedAccountPanel() {
  const { data: session, isPending } = useSession();
  const router = useRouter();

  if (isPending) return null;

  if (!session) {
    return (
      <div className="account-panel">
        <Link className="account-panel-action" href="/sign-in">
          Sign in
        </Link>
      </div>
    );
  }

  return (
    <div className="account-panel">
      <span className="account-panel-email">{session.user.email}</span>
      <button
        type="button"
        className="account-panel-action"
        onClick={async () => {
          await signOut();
          router.push("/sign-in");
          router.refresh();
        }}
      >
        Sign out
      </button>
    </div>
  );
}

"use client";

/**
 * Browser-side handle on the sign-in endpoints (hosted profile only).
 *
 * The JWT the Python backend verifies is never fetched here. Route handlers
 * read it from the session server-side in `backend-auth.ts`, so a bearer token
 * for the review API never reaches the page or its network log -- the same
 * reasoning ADR 0014 applies to BYOK provider keys.
 */

import { createAuthClient } from "better-auth/react";

export const authClient = createAuthClient();

export const { signIn, signUp, signOut, useSession, requestPasswordReset, resetPassword } = authClient;

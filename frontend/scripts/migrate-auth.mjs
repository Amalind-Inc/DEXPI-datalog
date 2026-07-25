/**
 * Create or update the hosted profile's account tables.
 *
 * Run before starting a hosted instance for the first time, and after
 * upgrading Better Auth. Migrations are not run at boot on purpose: a web
 * process altering its own schema on startup turns a rolling deploy into a
 * race, and hides schema changes from whoever is reviewing the release.
 *
 * The local profile never needs this. It has no accounts.
 *
 * Usage: node scripts/migrate-auth.mjs
 */

import { getMigrations } from "better-auth/db/migration";

import { getAuth } from "../lib/auth.ts";

const { runMigrations, toBeAdded, toBeCreated } = await getMigrations(getAuth().options);

if (toBeCreated.length === 0 && toBeAdded.length === 0) {
  console.log("auth schema is already up to date");
} else {
  for (const table of toBeCreated) console.log(`create table ${table.table}`);
  for (const table of toBeAdded) console.log(`alter table  ${table.table}`);
  await runMigrations();
  console.log("auth schema migrated");
}

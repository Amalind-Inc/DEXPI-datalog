import assert from "node:assert/strict";
import test from "node:test";

import {
  SOCIAL_PROVIDERS,
  configuredSocialProviders,
  enabledSocialProviders,
} from "./social-providers.ts";

test("no configuration means no providers, and that is not an error", () => {
  // The default self-hosted install signs up for nothing. Email and password
  // has to keep working with an empty environment.
  assert.deepEqual(configuredSocialProviders({}), {});
  assert.deepEqual(enabledSocialProviders({}), []);
});

test("a provider appears only when its whole credential pair is present", () => {
  const env = {
    GOOGLE_CLIENT_ID: "google-id",
    GOOGLE_CLIENT_SECRET: "google-secret",
  };

  assert.deepEqual(configuredSocialProviders(env), {
    google: { clientId: "google-id", clientSecret: "google-secret" },
  });
  assert.deepEqual(
    enabledSocialProviders(env).map((provider) => provider.id),
    ["google"],
  );
});

test("providers are independent: Apple alone does not need Google", () => {
  const env = {
    APPLE_CLIENT_ID: "apple-id",
    APPLE_CLIENT_SECRET: "apple-jwt",
  };

  assert.deepEqual(configuredSocialProviders(env), {
    apple: { clientId: "apple-id", clientSecret: "apple-jwt" },
  });
});

test("both configured means both offered, in a stable order", () => {
  const env = {
    APPLE_CLIENT_ID: "apple-id",
    APPLE_CLIENT_SECRET: "apple-jwt",
    GOOGLE_CLIENT_ID: "google-id",
    GOOGLE_CLIENT_SECRET: "google-secret",
  };

  // Declaration order, not environment order: the sign-in page must not
  // reshuffle its buttons because a deployment set its variables differently.
  assert.deepEqual(
    enabledSocialProviders(env).map((provider) => provider.id),
    ["google", "apple"],
  );
});

test("half a credential pair is refused loudly, naming the missing variable", () => {
  // Silence is the bad outcome here. Someone who set the client id has asked
  // for Google; rendering no button and logging nothing leaves them with
  // nothing to search for.
  assert.throws(
    () => configuredSocialProviders({ GOOGLE_CLIENT_ID: "google-id" }),
    (error: unknown) => {
      const message = error instanceof Error ? error.message : "";
      assert.match(message, /GOOGLE_CLIENT_SECRET/);
      assert.match(message, /GOOGLE_CLIENT_ID/);
      return true;
    },
  );

  assert.throws(
    () => configuredSocialProviders({ APPLE_CLIENT_SECRET: "apple-jwt" }),
    (error: unknown) => {
      const message = error instanceof Error ? error.message : "";
      assert.match(message, /APPLE_CLIENT_ID/);
      return true;
    },
  );
});

test("whitespace is not configuration", () => {
  // Empty strings arrive from `export GOOGLE_CLIENT_ID=` and from compose
  // files that declare a variable without a value. Treating those as set
  // would produce a button that fails at the provider instead of at boot.
  assert.deepEqual(
    configuredSocialProviders({ GOOGLE_CLIENT_ID: "   ", GOOGLE_CLIENT_SECRET: "" }),
    {},
  );
});

test("credentials are trimmed, because copied secrets carry newlines", () => {
  assert.deepEqual(
    configuredSocialProviders({
      GOOGLE_CLIENT_ID: " google-id\n",
      GOOGLE_CLIENT_SECRET: "google-secret ",
    }),
    { google: { clientId: "google-id", clientSecret: "google-secret" } },
  );
});

test("what reaches the browser carries no secret", () => {
  const env = {
    GOOGLE_CLIENT_ID: "google-id",
    GOOGLE_CLIENT_SECRET: "google-secret",
    APPLE_CLIENT_ID: "apple-id",
    APPLE_CLIENT_SECRET: "apple-jwt",
  };

  // This value is serialised into the sign-in page. Asserting the exact key
  // set is the point: a later field added to the provider table would ride
  // along into the HTML unless this test refuses it.
  for (const provider of enabledSocialProviders(env)) {
    assert.deepEqual(Object.keys(provider).sort(), ["id", "label"]);
  }

  const serialised = JSON.stringify(enabledSocialProviders(env));
  assert.doesNotMatch(serialised, /google-secret|apple-jwt|google-id|apple-id/);
});

test("the provider table names every id it offers", () => {
  // Guards the UI against an id with no label, which would render a button
  // saying "undefined".
  for (const provider of SOCIAL_PROVIDERS) {
    assert.ok(provider.label.length > 0, `${provider.id} needs a label`);
    assert.ok(provider.idVar.startsWith(provider.envPrefix));
    assert.ok(provider.secretVar.startsWith(provider.envPrefix));
  }
});

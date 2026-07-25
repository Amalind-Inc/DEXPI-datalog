import assert from "node:assert/strict";
import test from "node:test";

import { SMTP_VARS, isEmailConfigured, resetPasswordMessage, smtpSettings } from "./email.ts";

const complete = {
  SMTP_HOST: "smtp.example.com",
  SMTP_PORT: "587",
  SMTP_FROM: "pydexpi@example.com",
};

test("no configuration means no sender, and that is not an error", () => {
  // The default install sends no mail. Sign-in must still work, so this is an
  // absence rather than a failure.
  assert.equal(smtpSettings({}), null);
  assert.equal(isEmailConfigured({}), false);
});

test("host, port and from are enough: a relay need not want credentials", () => {
  // An internal relay or a sidecar on localhost commonly accepts unauthenticated
  // mail. Demanding a username would make those setups impossible to express.
  assert.deepEqual(smtpSettings(complete), {
    host: "smtp.example.com",
    port: 587,
    from: "pydexpi@example.com",
    secure: false,
    auth: null,
  });
});

test("a username and password are carried through when both are given", () => {
  const settings = smtpSettings({ ...complete, SMTP_USER: "mailer", SMTP_PASSWORD: "s3cret" });

  assert.deepEqual(settings?.auth, { user: "mailer", pass: "s3cret" });
});

test("port 465 is implicit TLS, and SMTP_SECURE can force it", () => {
  // Getting this wrong produces a hang rather than an error, which is a
  // miserable thing to debug, so it is inferred rather than asked for.
  assert.equal(smtpSettings({ ...complete, SMTP_PORT: "465" })?.secure, true);
  assert.equal(smtpSettings({ ...complete, SMTP_SECURE: "true" })?.secure, true);
  assert.equal(smtpSettings({ ...complete, SMTP_PORT: "587" })?.secure, false);
});

test("a half-configured sender is refused, naming what is missing", () => {
  // Someone who set SMTP_HOST has asked for mail. Quietly hiding the reset
  // link would leave them with no error and a feature that never appears.
  assert.throws(
    () => smtpSettings({ SMTP_HOST: "smtp.example.com" }),
    (error: unknown) => {
      const message = error instanceof Error ? error.message : "";
      assert.match(message, /SMTP_FROM/);
      return true;
    },
  );

  assert.throws(
    () => smtpSettings({ SMTP_FROM: "a@b.com", SMTP_PORT: "587" }),
    (error: unknown) => {
      assert.match(error instanceof Error ? error.message : "", /SMTP_HOST/);
      return true;
    },
  );
});

test("a password without a username is refused rather than sent as anonymous", () => {
  assert.throws(
    () => smtpSettings({ ...complete, SMTP_PASSWORD: "s3cret" }),
    (error: unknown) => {
      assert.match(error instanceof Error ? error.message : "", /SMTP_USER/);
      return true;
    },
  );
});

test("a port that is not a number is refused rather than coerced", () => {
  // `Number("587x")` is NaN and `Number("0")` is a port nothing listens on.
  // Either would reach the socket layer as a confusing failure far from the
  // typo that caused it.
  for (const port of ["not-a-port", "0", "99999", "-1", "58.7"]) {
    assert.throws(
      () => smtpSettings({ ...complete, SMTP_PORT: port }),
      (error: unknown) => {
        assert.match(error instanceof Error ? error.message : "", /SMTP_PORT/);
        return true;
      },
      `port ${JSON.stringify(port)} should be refused`,
    );
  }
});

test("an empty port is unset, not invalid", () => {
  // `SMTP_PORT=` in a compose file declares the variable without giving it a
  // value. Treating that as a typo would fail deployments that are merely
  // verbose, and it contradicts how every other setting here reads blanks.
  assert.equal(smtpSettings({ ...complete, SMTP_PORT: "  " })?.port, 587);
});

test("the port defaults to 587 when unset, which is submission", () => {
  assert.equal(smtpSettings({ SMTP_HOST: "smtp.example.com", SMTP_FROM: "a@b.com" })?.port, 587);
});

test("the reset message carries the link and never the token alone", () => {
  const url = "https://pid.example.com/reset-password?token=abc123";
  const message = resetPasswordMessage(url);

  assert.ok(message.subject.length > 0);
  assert.ok(message.text.includes(url));
  assert.ok(message.html.includes(url));
  // Someone who did not ask for this needs to know it is safe to ignore.
  assert.match(message.text, /did ?n[o']?t request|ignore/i);
});

test("the variable list matches what the settings reader actually reads", () => {
  // Documentation drifts; this keeps SMTP_VARS honest so the README table and
  // the error messages can be generated from one list.
  assert.deepEqual([...SMTP_VARS].sort(), [
    "SMTP_FROM",
    "SMTP_HOST",
    "SMTP_PASSWORD",
    "SMTP_PORT",
    "SMTP_SECURE",
    "SMTP_USER",
  ]);
});

# Security

## Reporting a vulnerability

Please report privately rather than in a public issue:
[open a security advisory](https://github.com/Harborfield/portlog/security/advisories/new).

That form is private to you and the maintainers. Include what you did, what
happened, and what you expected. A proof of concept is welcome but not
required to make a report worth sending.

Expect an acknowledgement within a week. This is a small project without an
on-call rotation, so please do not expect an hour-scale response. If a report
is valid we will agree a disclosure timeline with you rather than impose one.

## What this project is

`PortLog` is a demo and evaluation tool. Its own README says it should
not be used to verify production P&ID documents. Reports are welcome anyway,
but treat that framing as honest rather than defensive: this has not had a
security audit, and it should not be the only thing between an engineering
drawing and a decision that matters.

## Supported versions

Only the latest release and `main` receive fixes. There are no maintained
release branches.

## What is in scope

Anything that lets one signed-in user reach another user's data, leaks a model
provider credential, or lets an unauthenticated caller reach the review API in
the hosted profile. Sandbox escapes out of generated Datalog are firmly in
scope: the engine is meant to be the boundary that makes generated logic safe
to execute.

The local deployment profile has no accounts and no network services by
design. It assumes a single trusted operator on their own machine, so
"a local user can read local files" is not a vulnerability there.

## Known gaps, deliberately not treated as vulnerabilities

These are tracked as work, not secrets. Reporting them is not necessary,
though pointing out that one is worse than described certainly is.

- **Registration is open, and unverified when no mail relay is configured.**
  With SMTP set, an address must be confirmed before the account can be used.
  Without it, verification cannot be enforced -- requiring it with no way to
  send the link would lock every account out -- so a deployment reachable by
  strangers should configure SMTP or sit behind a private network.
- **Accounts live on the instance's disk.** The hosted profile keeps its
  account database in a SQLite file rather than the shared database, so a
  second instance would have its own users and its own JWT signing keys. Run
  one instance with a persistent volume until that changes.
- **No audit log of authentication events.** Sign-ins are not recorded.

## Credentials

Model provider keys are the sensitive material this project handles most.

In the **local** profile they never leave the browser (`localStorage`) except
as the body of the request that needs them, and the server stores nothing.

In the **hosted** profile a saved key is encrypted with AES-256-GCM before it
is written, with the owning user and provider bound in as associated data, so
a row copied to another user or provider fails to decrypt rather than
returning someone else's key. Encryption uses `HARBORFIELD_BYOK_SECRET`; a hosted
instance refuses to start without it rather than storing keys in the clear.

If you find a path where a credential reaches a log line, an artifact, an
error message, or an API response, that is a vulnerability and we want to know.

## Dependencies

Souffle is pinned by version and SHA-512 in both CI and the Docker image, and
the checksum is verified before the package is installed. Python and npm
dependencies are pinned in `pyproject.toml` and `frontend/package-lock.json`.

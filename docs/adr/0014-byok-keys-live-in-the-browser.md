# BYOK Keys Live in the Browser, Not on the Server

> **Scoped by ADR 0016 (bead 2afe.9).** What follows is the rule for the
> **local** deployment profile, where it still holds exactly as written. The
> hosted profile now keeps a per-user encrypted key store; the reasoning for
> that split is at the end of this document.

Provider credentials for bring-your-own-key operation are held in the
reviewer's own browser (`localStorage`, key `pydexpi.byok.v1`) and travel to
the Python review backend only as the `provider_settings` field of the turn
that needs them. The app persists no key server-side, has no key table, and
writes no key to a log or artifact directory.

Rejected alternatives: (1) a server-side key store, which would require an
account model, an encryption-at-rest story, and a rotation/revocation surface
that this single-tenant OSS deployment does not have; and (2) calling
providers straight from the browser, which OpenAI and Anthropic reject
cross-origin and which would put the credential in the page's network log.
The "Test key" button therefore probes the provider from a Next route handler
(`POST /api/byok/validate`), using the credential for one request and
discarding it.

Environment configuration (`OPENROUTER_API_KEY` and friends, read by
`readProviderSettingsFromEnv`) remains the fallback: a browser-supplied key
wins when present, the server's own configuration answers when it is not, and
the deterministic stub provider answers when neither exists. This keeps
scripted e2e runs (`PYDEXPI_DISABLE_BYOK=1`) and single-operator local runs
working unchanged while giving a hosted reader a way to bring their own model.

The model list offered per provider is a mirror of
`NATIVE_TOOL_CAPABLE_MODELS` (`pydexpi_datalog/llm/model_access.py`), not a
free-text field: grounded QA needs native tool calls, and the backend rejects
any pair outside that set. Payloads arriving from the browser are re-validated
against the same catalogue in the turn route before being forwarded, since
client-held keys mean client-controlled request data.

Governing related ADRs: 0006 (page-navigated app shell — API keys is an
account destination at the foot of the rail, not a primary work surface).

## The hosted profile: what changed and why (bead 2afe.9)

The first rejected alternative above was rejected on a premise that a hosted
deployment does not share. "This single-tenant OSS deployment does not have
an account model" was true when written and is false for the hosted profile,
which ADR 0016 gave accounts, a shared database, and object storage. Every
cost listed there is now already paid: the account model exists, the
encryption-at-rest story is one AES-GCM helper pair, and revocation is a
`DELETE`. What remains is the benefit, which is the point of the hosted
profile: a user who saved a key on their laptop finds it on their phone.

So the hosted profile stores per-user credentials, encrypted, in the same
libSQL database that holds the session index
(`pydexpi_datalog/workflow/provider_keys.py`). The local profile stores
nothing, and the bundle in `deployment.py` says so with a `build_key_store`
that returns `None` -- a profile's answer, not an unbuilt seam. The endpoints
answer 404 with `provider_keys.not_in_this_profile` there, which is honest:
on that deployment the resource does not exist.

Three properties were bought deliberately rather than assumed:

A **browser-supplied key still wins**. The precedence in `_effective_settings`
is session credential first, stored credential second. Sending a key with a
turn is a statement about that turn, and a saved key must not silently
override it.

The ciphertext is **bound to its owner and provider** as AES-GCM associated
data. A row copied into another user's name does not decrypt, so the
isolation rule survives write access to the database rather than depending on
every query remembering its `WHERE` clause.

A hosted deployment **refuses to start without `PYDEXPI_BYOK_SECRET`**. The
tempting fallbacks are both worse than refusing: storing in the clear is
obviously wrong, and generating a secret per instance is subtly wrong -- it
works on one machine and fails behind a load balancer or after a redeploy,
which is the class of bug ADR 0016 exists to prevent.

What did not change: the model catalogue is still the gate. A key saved
through the new endpoint is re-validated against
`require_native_tool_capable_model` before anything is written, for the same
reason the turn route re-validates a browser payload -- a client-held value
is a request, not a fact.

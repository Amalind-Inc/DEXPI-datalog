# BYOK Keys Live in the Browser, Not on the Server

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

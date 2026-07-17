# rmso.1 OpenRouter provider-configuration research

**Checked:** 2026-07-17

**Scope:** official OpenRouter and DeepSeek documentation and public first-party API
metadata only. Endpoint availability, prices, and advertised limits are live state and must
be snapshotted again immediately before the scored run.

## Conclusion

The locked configuration is currently implementable through OpenRouter Chat Completions.
The request should pin the single model slug, use the parameters below, and opt into router
metadata:

```json
{
  "model": "deepseek/deepseek-v4-flash",
  "temperature": 0,
  "reasoning": { "effort": "high" },
  "max_tokens": 8192,
  "provider": {
    "sort": "price",
    "require_parameters": true,
    "allow_fallbacks": true,
    "max_price": {
      "prompt": "<frozen USD per million input tokens>",
      "completion": "<frozen USD per million output tokens>"
    }
  }
}
```

Send `X-OpenRouter-Metadata: enabled`. Do not send `models`, `route: "fallback"`, or
an auto-router slug: those would open a model-fallback path rather than merely a
same-model provider fallback.

The numeric `max_price` rates are not fixed by the pre-registered protocol. They must be
chosen and frozen in the run configuration before any paid call. A defensible current
three-provider cutoff is discussed below, but selecting that cutoff is an implementation
decision, not a fact supplied by OpenRouter.

## Model identity and availability

OpenRouter's public model catalog currently contains the exact request ID
`deepseek/deepseek-v4-flash`, canonical version
`deepseek/deepseek-v4-flash-20260423`, a 1,048,576-token aggregate context length, and
advertised support for `temperature`, `max_tokens`, `reasoning`, and
`reasoning_effort`. Its reasoning metadata lists `high` and `xhigh` as supported efforts,
with `high` the default. These facts can be checked in the live
[`GET /api/v1/models` catalog](https://openrouter.ai/api/v1/models) and on the
[OpenRouter V4 Flash model page](https://openrouter.ai/deepseek/deepseek-v4-flash).

DeepSeek's own API uses the unprefixed direct-provider ID `deepseek-v4-flash`, enables
thinking by default, and accepts reasoning effort `high` or `max`; the OpenRouter slug is
therefore the correct gateway ID, while the unprefixed name is useful only when inspecting
the upstream transformation. [DeepSeek Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion/)

This proves availability at the time checked, not availability at run time. The harness
must preflight the public catalog and endpoint inventory immediately before the first
paid call and abort rather than substitute a model if the exact slug is absent.

## Reasoning and sampling

- Use one spelling only: `reasoning: {"effort": "high"}`. OpenRouter documents the
  top-level `reasoning_effort` shorthand as equivalent and says it cannot conflict with
  `reasoning.effort`; the structured form makes the intended setting explicit.
  [Chat Completions request reference](https://openrouter.ai/docs/api/api-reference/chat/send-chat-completion-request)
- `temperature: 0` is valid: OpenRouter documents the range as 0 through 2 and describes
  zero as producing the same response for a given input. The model and all currently
  listed endpoints advertise temperature support.
  [OpenRouter parameters](https://openrouter.ai/docs/api/reference/parameters)
- `temperature: 0` does **not** establish cross-provider or cross-version reproducibility.
  Provider fallback can change the serving backend, and the official documentation makes
  no promise that different backends are bit-identical. Preserve the resolved endpoint
  and model metadata for every call.
- `provider.require_parameters: true` is necessary because OpenRouter otherwise may
  ignore a parameter unsupported by a selected model/provider. With it, only providers
  that advertise support for all supplied parameters are eligible. This remains a
  capability-metadata guarantee, not proof of identical parameter semantics on every
  host. [Provider routing](https://openrouter.ai/docs/guides/routing/provider-selection)

## Provider sorting and same-model fallback

`provider.sort: "price"` disables OpenRouter's normal load balancing and tries eligible
providers in price order. `allow_fallbacks` defaults to `true`; setting it explicitly
records the protocol choice. OpenRouter then proceeds to another provider when an earlier
provider fails. [Provider sorting and fallbacks](https://openrouter.ai/docs/guides/routing/provider-selection)

Provider fallback and model fallback are distinct. A request containing only
`model: "deepseek/deepseek-v4-flash"` supplies one model to every eligible endpoint.
Model fallback requires an additional model-routing mechanism such as a `models` array.
The implementation should therefore reject any request containing multiple models and
assert after the call that:

1. top-level response `model` equals `deepseek/deepseek-v4-flash` (or its documented
   canonical version if OpenRouter returns that form); and
2. every `openrouter_metadata.attempts[].model` and the selected
   `openrouter_metadata.endpoints.available[]` model identifies the pinned V4 Flash
   model.

The opt-in router metadata records the requested model, selected provider/model, and each
fallback attempt; an `attempt` greater than one means an earlier provider failed.
[Router metadata response shape](https://openrouter.ai/docs/guides/features/router-metadata)

## Price constraint and current provider snapshot

`provider.max_price` is a hard eligibility filter. Its `prompt` and `completion` values
are USD per million tokens: for example, `{"prompt": 1, "completion": 2}` admits only
providers priced at no more than $1/M input and $2/M output. It can be combined with
`sort: "price"`. Provider `only`, `ignore`, and `order` are additional filters, but
`only` would unnecessarily shrink the fallback pool for this protocol.
[OpenRouter `max_price` documentation](https://openrouter.ai/docs/guides/routing/provider-selection#max-price)

At the time checked, the official endpoint inventory's three cheapest operational
endpoints that advertise the locked parameters were:

| Endpoint | Input $/M | Output $/M | Quantization | Advertised max completion |
| --- | ---: | ---: | --- | ---: |
| DeepInfra | 0.0900 | 0.1800 | FP4 | 65,536 |
| StreamLake | 0.0966 | 0.1932 | FP8 | 384,000 |
| GMICloud | 0.0980 | 0.1960 | FP8 | not published |

Source: [live V4 Flash endpoint inventory](https://openrouter.ai/api/v1/models/deepseek/deepseek-v4-flash-20260423/endpoints).

Thus a currently defensible ceiling of `prompt: 0.098`, `completion: 0.196` USD/M
retains three price-sorted fallback candidates while excluding higher-priced endpoints.
This is a snapshot-derived suggestion, not a stable property. The run must freeze its
chosen numbers, save the complete endpoint-inventory response used to choose them, verify
that at least two eligible operational endpoints remain, and calculate the pre-call
worst-case reservation from those frozen maxima. If no endpoint qualifies, the run must
stop; it must not relax the cap after seeing results.

## The 8,192-token combined output ceiling

Use `max_tokens: 8192`, rather than `max_completion_tokens`, for this model. OpenRouter's
generic Chat API now labels `max_tokens` deprecated in favor of `max_completion_tokens`,
but the live V4 Flash model and every current endpoint advertise `max_tokens`, not
`max_completion_tokens`. With `require_parameters: true`, using the advertised spelling
avoids accidentally filtering every provider.

OpenRouter defines `max_tokens` as an upper limit on tokens the model generates. DeepSeek
likewise defines it as the maximum generated chat-completion tokens, reports reasoning
tokens as a breakdown within completion tokens, and returns `finish_reason: "length"`
when the maximum is reached. Therefore 8,192 bounds reasoning plus visible generated
output, which is the protocol's intended combined ceiling.
[OpenRouter token-limit parameter](https://openrouter.ai/docs/api/reference/parameters#max-tokens),
[DeepSeek request and usage schema](https://api-docs.deepseek.com/api/create-chat-completion/)

Reasoning tokens are treated as output tokens and billed accordingly. The harness should
reject an ineligible response if `usage.completion_tokens > 8192`, record
`usage.completion_tokens_details.reasoning_tokens`, and preserve `finish_reason` and
`native_finish_reason`. [OpenRouter reasoning-token accounting](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens)

The 8,192 cap is below every currently published endpoint maximum (the smallest listed is
32,768), but endpoint limits are mutable and some providers publish `null`. The preflight
must rely on the explicit request cap and parameter eligibility, not infer a guarantee
from `top_provider.max_completion_tokens`, which is currently `null` in aggregate model
metadata.

## Required response and accounting capture

OpenRouter now includes a `usage` object automatically. For a non-streaming response it is
in the complete response; for streaming it appears in the final SSE event. Record at
least:

- response `id`, top-level `model`, choices, finish reasons, and full raw response;
- `usage.prompt_tokens`, `completion_tokens`, `total_tokens`;
- `usage.completion_tokens_details.reasoning_tokens` and cache-token details;
- `usage.cost` and `usage.cost_details`; and
- the full `openrouter_metadata` object, including requested model, strategy, selected
  endpoint, attempts, and provider/model for each attempt.

OpenRouter says `usage.cost` is the amount charged in credits, and its FAQ says the credit
system's base currency and all API prices are US dollars. That makes `usage.cost` the
immediate paid-USD accounting value for the protocol.
[Usage accounting](https://openrouter.ai/docs/cookbook/administration/usage-accounting),
[OpenRouter billing FAQ](https://openrouter.ai/docs/faq#credit-and-billing-systems)

For an independent audit record, use the response `id` with
`GET /api/v1/generation?id=...` and archive its `model`, `provider_name`, token counts,
`total_cost`, `native_tokens_reasoning`, service tier, and request ID. This endpoint is
the documented post-hoc source for resolved provider identity and generation cost.
[Generation metadata API](https://openrouter.ai/docs/api/api-reference/generations/get-generation)

Do not treat `cost_details.upstream_inference_cost` as the account charge. OpenRouter says
that field is the provider's upstream cost and that the generation lookup returns it only
meaningfully for BYOK calls; the protocol should use the OpenRouter account charge
(`usage.cost`, cross-checked against generation `total_cost`).

## Effective-setting audit limitation

Ordinary completion responses do not echo all effective provider-transformed settings.
The exact submitted request must therefore be preserved as the primary configuration
record. OpenRouter offers `debug.echo_upstream_body: true` to expose the transformed
upstream request, including each fallback attempt, but only for streaming requests and
explicitly as a development/debugging feature that may expose sensitive input.
[OpenRouter upstream-body debugging](https://openrouter.ai/docs/api/reference/errors-and-debugging#debugging)

If the scored harness needs to prove provider-side transformations rather than merely the
submitted locked settings plus `require_parameters`, it should enable streaming debug,
securely preserve every debug chunk, and still capture the final usage event. Otherwise,
the artifact must state the narrower claim: the locked values were submitted and the
selected provider advertised support; exact provider-internal application was not echoed.

## Current Terminus-KIRA compatibility gap

The current first-party multimedia-terminal-bench `TerminusKira` implementation cannot
enforce this protocol through constructor flags alone. Its native tool-call path builds
the LiteLLM request internally with `max_tokens: 32768`; when `reasoning_effort` is set,
it also overwrites the configured temperature with `1`. It does not expose the OpenRouter
`provider` object or metadata header in that request path. See the pinned upstream
[`_call_llm_with_tools` implementation](https://github.com/mm-tbench/multimedia-terminal-bench/blob/c96adc0001378d8e1f71a073a823f5d80bbbb1d0/mmtb_runtime/agent/terminus_kira.py#L637-L670).

Consequently, the existing external-agent command seam may still be used for scripted
tests, but it is ineligible for a live rmso.1 call until a controlled lower-level adapter
overrides and records the actual HTTP request, or the run pins a reviewed KIRA version
whose request path natively accepts every locked parameter. Passing optimistic
`--agent-kwarg` values without controlling this request construction would not satisfy
the pre-registered configuration.

## Uncertainties and run-time gates

- Availability, provider status, rates, quantization, context length, and endpoint output
  limits can change. Snapshot and validate them before spending.
- `require_parameters` relies on OpenRouter/provider capability metadata; it does not
  prove behavior equivalence among providers.
- Temperature zero does not eliminate variance caused by provider, quantization, backend,
  or model revisions.
- The aggregate model catalog does not publish a universal V4 Flash completion maximum;
  endpoint-specific values vary. The protocol's smaller explicit 8,192 cap is the only
  relevant run ceiling.
- `openrouter_metadata` is additive, so the decoder must ignore unknown fields. Cache
  hits omit it; if endpoint attribution is mandatory, disable/avoid response-cache replay
  or use the generation lookup and fail closed if resolved attribution remains absent.
- Numeric `max_price` rates remain an rmso.1 run-configuration choice. They must be
  frozen before the first paid episode and never adjusted in response to outcomes.

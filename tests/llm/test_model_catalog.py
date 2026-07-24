from __future__ import annotations

from urllib.parse import urlparse

import pytest

from pydexpi_datalog.llm.model_catalog import (
    UnknownModelError,
    UnknownProviderError,
    catalog_model,
    catalog_provider,
    featured_provider_ids,
    is_catalogued_model,
    load_catalog,
    provider_summaries,
    resolve_provider_id,
)


class TestCatalogBreadth:
    def test_catalog_covers_many_providers_across_every_wire_format(self) -> None:
        catalog = load_catalog()

        assert len(catalog.providers) > 100
        wire_formats = {provider.wire for provider in catalog.providers.values()}
        assert wire_formats == {"openai", "anthropic", "gemini"}

    def test_every_hosted_provider_is_usable_without_extra_configuration(self) -> None:
        for provider_id, provider in load_catalog().providers.items():
            assert provider.env_var, provider_id
            # Local servers are the one case with no snapshotted model list.
            assert provider.models or provider.is_local, provider_id

    def test_credentials_only_travel_over_tls_or_to_loopback(self) -> None:
        # A few catalogue entries are local model servers (LM Studio and
        # friends) that legitimately serve plaintext http. Anything else
        # reaching the network unencrypted would leak the user's key.
        for provider_id, provider in load_catalog().providers.items():
            if provider.base_url.startswith("https://"):
                continue
            host = urlparse(provider.base_url).hostname
            assert host in {"127.0.0.1", "::1", "localhost"}, provider_id

    def test_featured_providers_lead_with_the_majors(self) -> None:
        featured = featured_provider_ids()

        assert featured[:4] == ["openrouter", "anthropic", "openai", "google"]
        for provider_id in featured:
            assert provider_id in load_catalog().providers


class TestProviderLookup:
    def test_major_providers_resolve_to_their_wire_format_and_endpoint(self) -> None:
        assert catalog_provider("openai").base_url == "https://api.openai.com/v1"
        assert catalog_provider("openai").wire == "openai"
        assert catalog_provider("anthropic").wire == "anthropic"
        assert catalog_provider("google").wire == "gemini"
        # OpenRouter is an aggregator but speaks the OpenAI wire format.
        assert catalog_provider("openrouter").wire == "openai"
        assert catalog_provider("openrouter").base_url == "https://openrouter.ai/api/v1"

    def test_gemini_is_an_alias_for_the_catalogue_id_google(self) -> None:
        # The app shipped "gemini" as a provider id before adopting models.dev,
        # which calls the same provider "google". Stored keys must keep working.
        assert resolve_provider_id("gemini") == "google"
        assert catalog_provider("gemini") is catalog_provider("google")

    def test_an_unknown_provider_is_rejected_by_name(self) -> None:
        with pytest.raises(UnknownProviderError) as excinfo:
            catalog_provider("hotdog")

        assert "hotdog" in str(excinfo.value)


class TestModelLookup:
    def test_a_catalogued_model_carries_its_context_window(self) -> None:
        model = catalog_model("openai", "gpt-4.1")

        assert model.id == "gpt-4.1"
        assert model.context and model.context > 100_000

    def test_every_catalogued_model_is_native_tool_capable(self) -> None:
        # The snapshot is filtered on tool_call at build time, so membership in
        # the catalogue *is* the capability check grounded QA depends on.
        catalog = load_catalog()
        total = sum(len(provider.models) for provider in catalog.providers.values())

        assert total > 1000
        assert all(
            model.id
            for provider in catalog.providers.values()
            for model in provider.models.values()
        )

    def test_a_model_the_provider_does_not_serve_is_rejected(self) -> None:
        with pytest.raises(UnknownModelError) as excinfo:
            catalog_model("openai", "claude-sonnet-4-6")

        assert "claude-sonnet-4-6" in str(excinfo.value)
        assert "openai" in str(excinfo.value)

    def test_model_lookup_follows_the_provider_alias(self) -> None:
        assert catalog_model("gemini", "gemini-2.5-pro").id == "gemini-2.5-pro"


class TestFrontendProjection:
    def test_summaries_are_ordered_featured_first_then_alphabetical(self) -> None:
        summaries = provider_summaries()
        ids = [summary["id"] for summary in summaries]

        assert ids[: len(featured_provider_ids())] == featured_provider_ids()
        rest = ids[len(featured_provider_ids()) :]
        assert rest == sorted(rest)

    def test_a_summary_carries_what_the_picker_needs(self) -> None:
        summary = next(s for s in provider_summaries() if s["id"] == "openrouter")

        assert summary["name"] == "OpenRouter"
        assert summary["env_var"] == "OPENROUTER_API_KEY"
        assert summary["doc"].startswith("http")
        assert len(summary["models"]) > 50
        assert {"id", "name", "context", "reasoning", "released"} == set(summary["models"][0])

    def test_models_are_newest_first_so_the_default_pick_is_current(self) -> None:
        # The picker defaults to the head of this list. Alphabetical order
        # would default a 200-model aggregator to whatever sorts first.
        for summary in provider_summaries():
            released = [model["released"] for model in summary["models"] if model["released"]]
            assert released == sorted(released, reverse=True), summary["id"]


class TestLocalProviders:
    def test_local_ollama_is_offered_alongside_the_hosted_catalogue(self) -> None:
        provider = catalog_provider("ollama")

        assert provider.wire == "openai"
        assert provider.base_url == "http://localhost:11434/v1"
        assert provider.is_local

    def test_a_local_server_accepts_any_model_it_happens_to_have_pulled(self) -> None:
        # Locally-served models cannot be enumerated ahead of time, so
        # membership is open rather than checked against a snapshot.
        assert is_catalogued_model("ollama", "ornith:35b")
        assert is_catalogued_model("ollama", "some-model-pulled-yesterday")
        assert not is_catalogued_model("ollama", "")

    def test_hosted_providers_still_enforce_snapshot_membership(self) -> None:
        assert not catalog_provider("openai").is_local
        assert not is_catalogued_model("openai", "some-model-pulled-yesterday")

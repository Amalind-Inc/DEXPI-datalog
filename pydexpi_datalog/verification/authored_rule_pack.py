"""Authored rule-pack ingest and filesystem store.

Markdown pack ingest (bead pydexpi-datalog-1-1nox.3 / ADR 0013): user markdown
is stored immediately as an authored rule pack. Content may be advisory-only
or hybrid. Packs are attachable without a compile-on-upload gate. Uploads that
claim maintainer ``authoritative`` / bundled trust are rejected.
"""

from __future__ import annotations

from ..workflow.artifact_store import (
    ArtifactStore,
    InvalidArtifactKey,
    validate_key,
)
from .bundled_rule_pack import bundled_rule_packs
from .promote_advisory import (
    append_confirmed_rule_to_pack_markdown,
    propose_advisory_promotion,
)
from .rule_pack_markdown import parse_rule_pack_markdown


class AuthoredRulePackError(ValueError):
    """Raised when authored pack ingest is rejected."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class AuthoredRulePackStore:
    """Persist authored packs as canonical markdown under a store prefix."""

    def __init__(self, store: ArtifactStore, prefix: str = "authored_rule_packs") -> None:
        self._store = store
        self._prefix = prefix

    def _key(self, pack_id: str) -> str:
        """The key for a pack.

        `pack_id` comes from uploaded markdown, so a pack claiming an id like
        `../../escape` must not be able to write outside the prefix. The store
        refuses such a key; surface that as a pack-level rejection.
        """
        try:
            key = f"{self._prefix}/{pack_id}.md"
            validate_key(key)
        except InvalidArtifactKey as error:
            raise AuthoredRulePackError(
                "authored_pack.invalid_pack_id",
                f"Rule pack id is not a valid identifier: {pack_id!r}",
            ) from error
        return key

    def ingest(self, markdown: str) -> dict[str, object]:
        pack = parse_rule_pack_markdown(markdown)
        if pack["authoritative"] is True:
            raise AuthoredRulePackError(
                "authored_pack.authoritative_forbidden",
                "Authored rule packs cannot claim authoritative or bundled trust on upload.",
            )
        pack_id = str(pack["pack_id"])
        if any(str(entry["pack_id"]) == pack_id for entry in bundled_rule_packs()):
            raise AuthoredRulePackError(
                "authored_pack.pack_id_collision",
                f"Pack id '{pack_id}' collides with a repository-bundled rule pack.",
            )
        key = self._key(pack_id)
        if self._store.exists(key):
            raise AuthoredRulePackError(
                "authored_pack.already_exists",
                f"Authored rule pack '{pack_id}' already exists.",
            )

        # Force authored provenance regardless of uploaded prose claims.
        pack["authoritative"] = False
        pack["source"] = "user"
        self._store.write_text(key, markdown)
        # Re-parse from the store so markdown key matches stored bytes.
        stored = parse_rule_pack_markdown(self._store.read_text(key))
        stored["authoritative"] = False
        stored["source"] = "user"
        return stored

    def list_packs(self) -> list[dict[str, object]]:
        packs: list[dict[str, object]] = []
        for key in self._store.list(self._prefix, suffix=".md"):
            pack = parse_rule_pack_markdown(self._store.read_text(key))
            pack["authoritative"] = False
            pack["source"] = "user"
            packs.append(pack)
        return packs

    def get(self, pack_id: str) -> dict[str, object]:
        key = self._key(pack_id)
        if not self._store.exists(key):
            raise AuthoredRulePackError(
                "authored_pack.not_found",
                f"Unknown authored rule pack: {pack_id}",
            )
        pack = parse_rule_pack_markdown(self._store.read_text(key))
        pack["authoritative"] = False
        pack["source"] = "user"
        return pack

    def propose_promotion(
        self, *, pack_id: str, advisory_title: str
    ) -> dict[str, object]:
        pack = self.get(pack_id)
        return propose_advisory_promotion(pack=pack, advisory_title=advisory_title)

    def confirm_promotion(
        self, *, pack_id: str, draft: dict[str, object]
    ) -> dict[str, object]:
        if str(draft.get("pack_id", pack_id)) != pack_id:
            raise AuthoredRulePackError(
                "authored_pack.draft_pack_mismatch",
                "Draft pack_id does not match the target authored pack.",
            )
        if draft.get("trust") != "pending_author_confirmation":
            raise AuthoredRulePackError(
                "authored_pack.draft_not_pending",
                "Only drafts pending author confirmation can be confirmed.",
            )
        if draft.get("authoritative") is True:
            raise AuthoredRulePackError(
                "authored_pack.authoritative_forbidden",
                "Authored rule packs cannot claim authoritative or bundled trust.",
            )

        key = self._key(pack_id)
        if not self._store.exists(key):
            raise AuthoredRulePackError(
                "authored_pack.not_found",
                f"Unknown authored rule pack: {pack_id}",
            )
        current = parse_rule_pack_markdown(self._store.read_text(key))
        rule_id = str(draft.get("rule_id") or "")
        if any(str(rule["rule_id"]) == rule_id for rule in current["rules"]):  # type: ignore[union-attr]
            raise AuthoredRulePackError(
                "authored_pack.rule_already_exists",
                f"Rule '{rule_id}' already exists in pack '{pack_id}'.",
            )

        executable = draft.get("executable_logic")
        if not isinstance(executable, dict) or not isinstance(
            executable.get("content"), str
        ):
            raise AuthoredRulePackError(
                "authored_pack.draft_incomplete",
                "Draft must include executable_logic.content for confirmation.",
            )

        confirmed_draft = dict(draft)
        confirmed_draft["trust"] = "author_confirmed"
        confirmed_draft["authoritative"] = False
        updated_markdown = append_confirmed_rule_to_pack_markdown(
            self._store.read_text(key),
            draft=confirmed_draft,
        )
        self._store.write_text(key, updated_markdown)
        return self.get(pack_id)

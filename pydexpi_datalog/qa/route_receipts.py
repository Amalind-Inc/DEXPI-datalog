"""Backend-owned route outcomes and scoped receipts for grounded QA."""

from __future__ import annotations

import hmac
import json
import hashlib
import os
import re
import secrets
import unicodedata
from collections.abc import Mapping
from dataclasses import asdict, dataclass

from pydexpi_datalog.qa.structured_intent import normalize_structured_intent


ROUTE_POLICY_VERSION = "grounded-qa-route-policy/1"

ROUTE_TEMPLATE_SUCCESS = "template_success"
ROUTE_TEMPLATE_NO_FIT = "template_no_fit"
ROUTE_TEMPLATE_BINDING_REJECTED = "template_binding_rejected"
ROUTE_TEMPLATE_FAITHFULNESS_FAILURE = "template_faithfulness_failure"
ROUTE_TEMPLATE_EXECUTION_FAILURE = "template_execution_failure"
ROUTE_GENERATED_QUERY_AUTHORIZED = "generated_query_authorized"
ROUTE_DEONTIC_ABSTENTION = "deontic_abstention"
ROUTE_CLARIFICATION = "clarification"
ROUTE_REASONING_ENGINE_UNAVAILABLE = "reasoning_engine_unavailable"

_RECEIPT_ELIGIBLE_OUTCOMES = frozenset(
    {
        ROUTE_TEMPLATE_NO_FIT,
        ROUTE_TEMPLATE_FAITHFULNESS_FAILURE,
        ROUTE_GENERATED_QUERY_AUTHORIZED,
    }
)
_CONFIGURED_SIGNING_SECRET = os.environ.get("PYDEXPI_ROUTE_RECEIPT_SECRET")
_RECEIPT_SIGNING_KEY = (
    _CONFIGURED_SIGNING_SECRET.encode("utf-8")
    if _CONFIGURED_SIGNING_SECRET
    else secrets.token_bytes(32)
)
_DEONTIC_PATTERN = re.compile(
    r"\b(?:allow(?:ed|able)?|authori[sz](?:e|ed|ation)|permit(?:ted|s|ting)?|"
    r"permission|exempt(?:ion|ed|ions)?|exception(?:s)?|waiver(?:s)?|"
    r"notwithstanding|overrid(?:e|es|den|ing))\b|"
    r"\bmay\s+(?:i|we|an?\s+operator|the\s+operator|users?)\b|"
    r"\bcan\s+(?:this|that|it|i|we|an?\s+operator|the\s+operator)\s+"
    r"(?:be\s+)?(?:bypass(?:ed)?|overrid(?:e|den)|ignore(?:d)?|operate(?:d)?|"
    r"start(?:ed)?|run)\b"
)


@dataclass(frozen=True)
class RouteContext:
    normalized_intent: str
    source_snapshot_id: str
    template_catalog_version: str
    policy_version: str


@dataclass(frozen=True)
class RouteReceipt:
    receipt_id: str
    route_outcome: str
    intent_digest: str
    source_snapshot_id: str
    template_catalog_version: str
    policy_version: str
    structured_intent_json: str
    signature: str

    def artifact(self) -> dict[str, str]:
        return asdict(self)


class RouteReceiptAuthority:
    """Issue opaque receipts and validate them against the active request context."""

    def __init__(self) -> None:
        self._context: RouteContext | None = None
        self._receipts: dict[str, tuple[RouteReceipt, RouteContext]] = {}
        self._active_receipt_id: str | None = None

    def begin_request(
        self,
        *,
        intent: str,
        source_snapshot_id: str,
        template_catalog_version: str,
        policy_version: str = ROUTE_POLICY_VERSION,
        resume_receipt: dict[str, object] | None = None,
    ) -> None:
        context = RouteContext(
            normalized_intent=normalize_semantic_intent(intent),
            source_snapshot_id=source_snapshot_id,
            template_catalog_version=template_catalog_version,
            policy_version=policy_version,
        )
        if context != self._context:
            self._active_receipt_id = None
        self._context = context
        if resume_receipt is not None:
            self._restore_receipt(resume_receipt)

    def record_backend_outcome(
        self,
        outcome: str,
        *,
        structured_intent: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        if self._context is None:
            return {
                "status": "route_context_missing",
                "route_outcome": outcome,
                "route_receipt": None,
            }
        if outcome not in _RECEIPT_ELIGIBLE_OUTCOMES:
            self._active_receipt_id = None
            return {
                "status": "route_outcome_recorded",
                "route_outcome": outcome,
                "route_receipt": None,
            }
        normalized_structured_intent: dict[str, object] | None = None
        if structured_intent is not None:
            normalized_structured_intent, diagnostics = normalize_structured_intent(
                structured_intent
            )
            if diagnostics:
                self._active_receipt_id = None
                return {
                    "status": "route_structured_intent_invalid",
                    "route_outcome": outcome,
                    "route_receipt": None,
                    "diagnostics": diagnostics,
                }

        receipt_fields = {
            "receipt_id": secrets.token_hex(16),
            "route_outcome": outcome,
            "intent_digest": _digest(self._context.normalized_intent),
            "source_snapshot_id": self._context.source_snapshot_id,
            "template_catalog_version": self._context.template_catalog_version,
            "policy_version": self._context.policy_version,
            "structured_intent_json": _canonical_intent_json(
                normalized_structured_intent
            ),
        }
        receipt = RouteReceipt(
            **receipt_fields,
            signature=_sign_receipt_fields(receipt_fields),
        )
        self._receipts[receipt.receipt_id] = (receipt, self._context)
        self._active_receipt_id = receipt.receipt_id
        return {
            "status": "route_receipt_issued",
            "route_outcome": outcome,
            "route_receipt": receipt.artifact(),
        }

    def _restore_receipt(self, artifact: dict[str, object]) -> None:
        if self._context is None:
            return
        fields = {
            name: str(artifact.get(name, ""))
            for name in (
                "receipt_id",
                "route_outcome",
                "intent_digest",
                "source_snapshot_id",
                "template_catalog_version",
                "policy_version",
                "structured_intent_json",
            )
        }
        signature = str(artifact.get("signature", ""))
        expected_context = {
            "intent_digest": _digest(self._context.normalized_intent),
            "source_snapshot_id": self._context.source_snapshot_id,
            "template_catalog_version": self._context.template_catalog_version,
            "policy_version": self._context.policy_version,
        }
        if (
            fields["route_outcome"] not in _RECEIPT_ELIGIBLE_OUTCOMES
            or any(fields[name] != value for name, value in expected_context.items())
            or not hmac.compare_digest(signature, _sign_receipt_fields(fields))
        ):
            return
        receipt = RouteReceipt(**fields, signature=signature)
        self._receipts[receipt.receipt_id] = (receipt, self._context)
        self._active_receipt_id = receipt.receipt_id

    def active_receipt(self) -> dict[str, str] | None:
        if self._active_receipt_id is None or self._context is None:
            return None
        stored = self._receipts.get(self._active_receipt_id)
        if stored is None:
            return None
        receipt, issued_context = stored
        if issued_context != self._context:
            self._active_receipt_id = None
            return None
        return receipt.artifact()

    def active_structured_intent(self) -> dict[str, object] | None:
        active = self.active_receipt()
        if active is None or not active["structured_intent_json"]:
            return None
        try:
            parsed = json.loads(active["structured_intent_json"])
        except json.JSONDecodeError:
            return None
        normalized, diagnostics = normalize_structured_intent(parsed)
        return None if diagnostics else normalized

    def validates(self, receipt_id: str) -> bool:
        active = self.active_receipt()
        return active is not None and active["receipt_id"] == receipt_id

    def matches_active_intent(self, intent: str) -> bool:
        return (
            self._context is not None
            and self._context.normalized_intent == normalize_semantic_intent(intent)
        )


def normalize_semantic_intent(intent: str) -> str:
    normalized = unicodedata.normalize("NFKC", intent).casefold()
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized.rstrip(".?!")


def is_deontic_or_defeasible_request(intent: str) -> bool:
    return _DEONTIC_PATTERN.search(normalize_semantic_intent(intent)) is not None


def source_snapshot_identity(graph_facts: object) -> str:

    canonical = json.dumps(
        graph_facts,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return _digest(canonical)


def _canonical_intent_json(value: Mapping[str, object] | None) -> str:
    if value is None:
        return ""
    return json.dumps(
        dict(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def _sign_receipt_fields(fields: dict[str, str]) -> str:
    payload = json.dumps(fields, sort_keys=True, separators=(",", ":"))
    return hmac.new(
        _RECEIPT_SIGNING_KEY,
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

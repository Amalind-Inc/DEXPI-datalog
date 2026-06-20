from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from .legacy_xml_normalization import LegacyXmlNormalizationResult


CORE_PREDICATES = {"has_tag"}


@dataclass(frozen=True)
class RuleEvaluationResult:
    findings: list[dict[str, object]]
    diagnostics: list[dict[str, str]]


def evaluate_rule_pack(
    rule_pack_path: Path, normalization_result: LegacyXmlNormalizationResult
) -> RuleEvaluationResult:
    raw_rule_pack = json.loads(rule_pack_path.read_text(encoding="utf-8"))
    diagnostics = validate_rule_pack(raw_rule_pack)
    if diagnostics:
        return RuleEvaluationResult(findings=[], diagnostics=diagnostics)

    findings = evaluate_rules(raw_rule_pack["rules"], normalization_result)
    return RuleEvaluationResult(findings=findings, diagnostics=[])


def validate_rule_pack(raw_rule_pack: object) -> list[dict[str, str]]:
    diagnostics: list[dict[str, str]] = []
    if not isinstance(raw_rule_pack, dict):
        diagnostics.append(
            error_diagnostic(
                code="rule_pack.invalid_type",
                message="Rule pack root must be an object.",
                path="rule_pack",
            )
        )
        return diagnostics

    rules = raw_rule_pack.get("rules")
    if not isinstance(rules, list):
        diagnostics.append(
            error_diagnostic(
                code="rule_pack.invalid_rules",
                message="rule_pack.rules must be a list.",
                path="rules",
            )
        )
        return diagnostics

    for index, rule in enumerate(rules):
        diagnostics.extend(validate_rule(rule, index))

    return diagnostics


def validate_rule(rule: object, index: int) -> list[dict[str, str]]:
    diagnostics: list[dict[str, str]] = []
    if not isinstance(rule, dict):
        diagnostics.append(
            error_diagnostic(
                code="rule_pack.invalid_rule",
                message="Each rule must be an object.",
                path=f"rules[{index}]",
            )
        )
        return diagnostics

    conditions = rule.get("conditions")
    if not isinstance(conditions, dict):
        diagnostics.append(
            error_diagnostic(
                code="rule_pack.invalid_conditions",
                message="Rule conditions must be an object.",
                path=f"rules[{index}].conditions",
            )
        )
        return diagnostics

    all_conditions = conditions.get("all")
    if not isinstance(all_conditions, list):
        diagnostics.append(
            error_diagnostic(
                code="rule_pack.invalid_condition_tree",
                message="Rule conditions must provide an 'all' list.",
                path=f"rules[{index}].conditions.all",
            )
        )
        return diagnostics

    for predicate_index, predicate_node in enumerate(all_conditions):
        diagnostics.extend(
            validate_predicate(predicate_node, index=index, predicate_index=predicate_index)
        )

    return diagnostics


def validate_predicate(
    predicate_node: object, *, index: int, predicate_index: int
) -> list[dict[str, str]]:
    diagnostics: list[dict[str, str]] = []
    if not isinstance(predicate_node, dict):
        diagnostics.append(
            error_diagnostic(
                code="rule_pack.invalid_predicate",
                message="Each predicate node must be an object.",
                path=f"rules[{index}].conditions.all[{predicate_index}]",
            )
        )
        return diagnostics

    predicate = predicate_node.get("predicate")
    if predicate not in CORE_PREDICATES:
        diagnostics.append(
            error_diagnostic(
                code="rule_pack.unknown_predicate",
                message=f"Unknown predicate: {predicate}",
                path=f"rules[{index}].conditions.all[{predicate_index}].predicate",
            )
        )

    return diagnostics


def evaluate_rules(
    rules: list[dict[str, object]], normalization_result: LegacyXmlNormalizationResult
) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []

    for rule in rules:
        rule_id = rule["rule_id"]
        severity = rule["severity"]
        predicate_node = rule["conditions"]["all"][0]
        predicate = predicate_node["predicate"]

        if predicate != "has_tag":
            continue

        for normalized_object in normalization_result.normalized_objects:
            if not normalized_object.normalized_tag:
                continue
            findings.append(
                {
                    "rule_id": rule_id,
                    "severity": severity,
                    "affected_object_ids": [normalized_object.object_id],
                    "evidence_trail": {
                        "primary_rule": rule_id,
                        "supporting_facts": [
                            {
                                "predicate": "has_tag",
                                "object_id": normalized_object.object_id,
                                "normalized_tag": normalized_object.normalized_tag,
                            }
                        ],
                    },
                }
            )

    return findings


def error_diagnostic(*, code: str, message: str, path: str) -> dict[str, str]:
    return {
        "code": code,
        "severity": "error",
        "message": message,
        "path": path,
    }

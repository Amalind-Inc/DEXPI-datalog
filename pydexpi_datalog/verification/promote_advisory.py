"""Promote advisory pack guidance into draft / confirmed authored rules.

Bead pydexpi-datalog-1-1nox.6 / ADR 0013: promotion drafts Datalog only inside
the expressible predicate island. Outside the island, abstain and keep the
clause advisory. Author confirmation persists the exact displayed fence under
author-confirmed rule trust (never bundled trust).
"""

from __future__ import annotations

import re
from dataclasses import dataclass


OUTSIDE_ISLAND_MARKERS = (
    "adequate",
    "adequacy",
    "sufficient",
    "worst-case",
    "worst case",
    "unless",
    "should consider",
    "engineering judgment",
)

COMPONENT_PRESENCE_RE = re.compile(
    r"centrifugal\s*pump",
    re.IGNORECASE,
)
PRESENCE_INTENT_RE = re.compile(
    r"\b(must include|include at least one|at least one|must have|is present|be present)\b",
    re.IGNORECASE,
)

PUMP_PRESENT_FENCE = """\
.decl pump(id:symbol)
pump(id) :- node_label(id, "CentrifugalPump").

.decl rule_result(subject_id:symbol, result_type:symbol)
rule_result(id, "pass") :- pump(id).

.decl rule_message(subject_id:symbol, message:symbol)
rule_message(id, "A centrifugal pump is present in the prepared graph.") :- pump(id).

.decl rule_subject_attr(subject_id:symbol, attr:symbol, value:symbol)
rule_subject_attr(id, "pump_id", id) :- pump(id).
rule_subject_attr(id, "discharge_nozzle_id", "n/a") :- pump(id).

.decl rule_engine_attr(subject_id:symbol, key:symbol, value:symbol)
rule_engine_attr(id, "engine", "souffle") :- pump(id).

.output rule_result
.output rule_message
.output rule_subject_attr
.output rule_engine_attr
"""


@dataclass(frozen=True)
class PromoteAbstention:
    code: str
    message: str


def classify_expressible_island(clause_text: str) -> str:
    """Return ``in_island`` or ``outside_island`` for an advisory clause body."""
    lowered = clause_text.lower()
    if any(marker in lowered for marker in OUTSIDE_ISLAND_MARKERS):
        return "outside_island"
    if COMPONENT_PRESENCE_RE.search(clause_text) and PRESENCE_INTENT_RE.search(
        clause_text
    ):
        return "in_island"
    return "outside_island"


def propose_advisory_promotion(
    *,
    pack: dict[str, object],
    advisory_title: str,
) -> dict[str, object]:
    """Propose a draft rule from one advisory section, or abstain."""
    section = _find_advisory(pack, advisory_title)
    if section is None:
        raise ValueError(f"unknown advisory section: {advisory_title}")
    body = str(section.get("body") or "")
    if classify_expressible_island(body) != "in_island":
        return {
            "status": "abstained",
            "code": "promote.outside_island",
            "message": (
                "This clause is outside the expressible predicate island "
                "(topology/reachability, component/class presence, or numeric "
                "attribute thresholds). It remains advisory pack guidance."
            ),
            "advisory_title": advisory_title,
        }

    rule_id = _slug_rule_id(advisory_title)
    restatement = (
        "If the prepared diagram is under review, then it must include at least "
        "one node labeled CentrifugalPump."
    )
    fence = PUMP_PRESENT_FENCE
    return {
        "status": "draft",
        "draft": {
            "pack_id": str(pack["pack_id"]),
            "advisory_title": advisory_title,
            "rule_id": rule_id,
            "title": advisory_title,
            "trust": "pending_author_confirmation",
            "authoritative": False,
            "outcomes": ["satisfied", "violated", "indeterminate"],
            "restatement": {
                "kind": "plain",
                "plain_language_meaning": restatement,
            },
            "executable_logic": {
                "kind": "datalog",
                "language": "souffle_datalog",
                "content": fence,
                "inspectable": True,
                "editable": False,
                "disclosure": "collapsed",
            },
        },
    }


def render_confirmed_rule_markdown(draft: dict[str, object]) -> str:
    """Render a confirmed rule section (restatement first, fence disclosed)."""
    title = str(draft["title"])
    rule_id = str(draft["rule_id"])
    restatement = draft["restatement"]
    meaning = (
        str(restatement.get("plain_language_meaning", "")).strip()
        if isinstance(restatement, dict)
        else ""
    )
    fence = str(draft["executable_logic"]["content"]).rstrip()  # type: ignore[index]
    return (
        f"## {title} {{#{rule_id}}}\n"
        f"\n"
        f"{meaning}\n"
        f"\n"
        f"<!-- rule_trust: author_confirmed -->\n"
        f"\n"
        f"```souffle-datalog\n"
        f"{fence}\n"
        f"```\n"
    )


def append_confirmed_rule_to_pack_markdown(
    markdown: str,
    *,
    draft: dict[str, object],
) -> str:
    """Append a confirmed rule section and bump pack version in frontmatter."""
    rule_block = render_confirmed_rule_markdown(draft).rstrip() + "\n"
    text = markdown.rstrip() + "\n\n" + rule_block
    return _bump_frontmatter_version(text)


def _bump_frontmatter_version(markdown: str) -> str:
    lines = markdown.splitlines()
    if not lines or lines[0].strip() != "---":
        return markdown
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            for meta_index in range(1, index):
                if lines[meta_index].startswith("version:"):
                    try:
                        current = int(lines[meta_index].split(":", 1)[1].strip())
                    except ValueError:
                        current = 1
                    lines[meta_index] = f"version: {current + 1}"
                    break
            return "\n".join(lines) + ("\n" if markdown.endswith("\n") else "")
    return markdown


def _find_advisory(
    pack: dict[str, object], advisory_title: str
) -> dict[str, object] | None:
    for section in pack.get("advisory_guidance") or []:
        if isinstance(section, dict) and str(section.get("title")) == advisory_title:
            return section
    return None


def _slug_rule_id(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", title.strip().lower()).strip("_")
    return slug or "promoted_rule"

"""Arm T prebuilt Datalog template pack (design-lock v3, bead lx6p).

The model's only authored surface is a routing JSON::

    {"category": "<template id>", "parameters": {...}}

Every template body below is frozen, internally reviewed code building on the
shared ``graph_topology_semantics.dl`` IDB. Parameters are validated against
the drawing's inspection vocabulary plus any explicit closed class list in the
question before anything is rendered, and rendered programs flow through the
unchanged ``run_query.py`` checkpoint lifecycle. SMEs review the plain-language
``description`` fields, never the Datalog.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

DEFAULT_INCLUDE_DIR = "/input"

ATTACHMENT_ROLES = (
    "sourceItem",
    "targetItem",
    "sourceNode",
    "targetNode",
)
ATTACHMENT_MODES = ("attached", "unattached")
COUNT_COMPARATORS = {"at_least": ">=", "exactly": "=", "at_most": "<="}
SCOPE_VALUES = ("piping", "any")
DIRECTION_VALUES = ("directed", "undirected")

_MAX_VOCABULARY_IN_ERROR = 40
_CLOSED_CLASS_CUE = re.compile(
    r"^\s*(?:any|one)\s+of\s+", re.IGNORECASE
)
_CLASS_LIST_SEPARATOR = re.compile(r",|\b(?:and|or)\b", re.IGNORECASE)
_DEXPI_CLASS_IDENTIFIER = re.compile(r"\b[A-Z][A-Za-z0-9]*\b")


@dataclass(frozen=True)
class SlotSpec:
    """One typed parameter slot of a template."""

    kind: str  # label_set | tag_set | role_set | mode | comparator | threshold
    required: bool = True


@dataclass(frozen=True)
class Template:
    id: str
    description: str
    slots: dict[str, SlotSpec] = field(default_factory=dict)


TEMPLATE_PACK: dict[str, Template] = {
    template.id: template
    for template in (
        Template(
            id="entity_lookup",
            description=(
                "Find every component of the given classes and/or with the "
                "given tag names."
            ),
            slots={
                "labels": SlotSpec("label_set", required=False),
                "tags": SlotSpec("tag_set", required=False),
            },
        ),
        Template(
            id="attachment",
            description=(
                "Find components of the given classes that are (or are not) "
                "attached to anything through a piping reference."
            ),
            slots={
                "entity_labels": SlotSpec("label_set"),
                "mode": SlotSpec("mode"),
                "roles": SlotSpec("role_set", required=False),
            },
        ),
        Template(
            id="reachability",
            description=(
                "Find components of the target classes that can be reached "
                "from any component of the source classes. scope=piping "
                "(default) follows only piping-connection edges (incl. "
                "nozzles); scope=any follows every edge (use when the "
                "question says any directed edge / through any intermediate "
                "objects, e.g. instrumentation-and-control monitoring paths). "
                "direction=directed (default) follows edges source-to-target; "
                "direction=undirected follows a path in either direction (use "
                "when the question says in either direction)."
            ),
            slots={
                "source_labels": SlotSpec("label_set"),
                "target_labels": SlotSpec("label_set"),
                "scope": SlotSpec("scope", required=False),
                "direction": SlotSpec("direction", required=False),
            },
        ),
        Template(
            id="guarded_reachability",
            description=(
                "Find components of the target classes that CANNOT be "
                "reached from any component of the source classes - e.g. "
                "valves not monitored by any instrumentation function, or "
                "equipment with no piping path to any pump. scope=piping "
                "(default) follows only piping-connection edges (incl. "
                "nozzles); scope=any follows every edge (use for any "
                "directed edge / through any intermediate objects, e.g. "
                "I&C monitoring coverage). direction=directed (default) "
                "follows edges source-to-target; direction=undirected follows "
                "a path in either direction (use when the question says in "
                "either direction, e.g. process piping connectivity)."
            ),
            slots={
                "source_labels": SlotSpec("label_set"),
                "target_labels": SlotSpec("label_set"),
                "scope": SlotSpec("scope", required=False),
                "direction": SlotSpec("direction", required=False),
            },
        ),
        Template(
            id="class_count",
            description=(
                "Check how many components of the given classes exist; the "
                "members are the evidence when the count condition holds."
            ),
            slots={
                "labels": SlotSpec("label_set"),
                "comparator": SlotSpec("comparator"),
                "threshold": SlotSpec("threshold"),
            },
        ),
        Template(
            id="policy_abstention",
            description=(
                "Permission or defeasible-policy questions cannot be soundly "
                "decided from monotone drawing facts; abstain mechanically."
            ),
            slots={},
        ),
    )
}


def explicit_label_requirements(question: str) -> frozenset[str]:
    """Return DEXPI-style class identifiers from explicit closed lists.

    Detection is deliberately conservative: a parenthetical group must either
    start with ``any of`` / ``one of`` or be entirely composed of two or more
    class identifiers joined by commas or conjunctions. Ambiguous prose
    remains a reasoning and faithfulness concern rather than being guessed.
    """
    required: set[str] = set()
    for parenthetical in re.findall(r"\(([^()]*)\)", question):
        cue = _CLOSED_CLASS_CUE.match(parenthetical)
        body = parenthetical[cue.end():] if cue else parenthetical
        if cue is None and _CLASS_LIST_SEPARATOR.search(body) is None:
            continue
        labels = _DEXPI_CLASS_IDENTIFIER.findall(body)
        if len(labels) < (1 if cue else 2):
            continue
        residue = _DEXPI_CLASS_IDENTIFIER.sub("", body)
        residue = _CLASS_LIST_SEPARATOR.sub("", residue)
        residue = re.sub(r"[\s/]+", "", residue)
        if residue:
            continue
        required.update(labels)
    return frozenset(required)


def routing_vocabulary(
    inspection_json: str,
    *,
    additional_labels: frozenset[str] = frozenset(),
) -> dict[str, frozenset[str]]:
    """Extract the closed validation vocabulary from graph inspection.

    Explicitly enumerated question labels are valid even when absent from the
    current drawing: reusable rules must preserve that scope for replay.
    """
    inspection = json.loads(inspection_json)
    nodes = inspection.get("nodes") or []
    labels = frozenset(
        str(node["label"]) for node in nodes if node.get("label")
    ) | additional_labels
    tags = frozenset(
        str(node["tag_name"]) for node in nodes if node.get("tag_name")
    )
    return {"labels": labels, "tags": tags}


def _vocabulary_hint(values: frozenset[str]) -> str:
    shown = sorted(values)[:_MAX_VOCABULARY_IN_ERROR]
    return ", ".join(shown)


def _validate_string_list(name: str, value: object) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        return [f"{name} must be a non-empty list of strings"]
    if not value:
        return [f"{name} must not be empty"]
    return []


def validate_routing(
    routing: object,
    vocabulary: dict[str, frozenset[str]],
    *,
    required_labels: frozenset[str] = frozenset(),
) -> list[str]:
    """Return every validation error for a routing JSON (empty = valid)."""
    if not isinstance(routing, dict):
        return ["routing must be a JSON object with category and parameters"]
    category = routing.get("category")
    if category not in TEMPLATE_PACK:
        return [
            f"unknown category {category!r}; valid categories: "
            + ", ".join(sorted(TEMPLATE_PACK))
        ]
    template = TEMPLATE_PACK[category]
    parameters = routing.get("parameters") or {}
    if not isinstance(parameters, dict):
        return ["parameters must be a JSON object"]

    errors: list[str] = []
    for name in parameters:
        if name not in template.slots:
            errors.append(
                f"{category} does not take parameter {name!r}; allowed: "
                + (", ".join(sorted(template.slots)) or "none")
            )
    for name, spec in template.slots.items():
        value = parameters.get(name)
        if value is None:
            if spec.required:
                errors.append(f"{category} requires parameter {name!r}")
            continue
        if spec.kind in ("label_set", "tag_set", "role_set"):
            list_errors = _validate_string_list(name, value)
            if list_errors:
                errors.extend(list_errors)
                continue
            domain: frozenset[str]
            if spec.kind == "label_set":
                domain = vocabulary["labels"]
                domain_name = "drawing label vocabulary"
            elif spec.kind == "tag_set":
                domain = vocabulary["tags"]
                domain_name = "drawing tag vocabulary"
            else:
                domain = frozenset(ATTACHMENT_ROLES)
                domain_name = "reference roles"
            unknown = [item for item in value if item not in domain]
            if unknown:
                errors.append(
                    f"{name} contains values not in the {domain_name}: "
                    + ", ".join(sorted(unknown))
                    + f"; valid values: {_vocabulary_hint(domain)}"
                )
        elif spec.kind == "mode":
            if value not in ATTACHMENT_MODES:
                errors.append(
                    f"{name} must be one of: " + ", ".join(ATTACHMENT_MODES)
                )
        elif spec.kind == "comparator":
            if value not in COUNT_COMPARATORS:
                errors.append(
                    f"{name} must be one of: "
                    + ", ".join(sorted(COUNT_COMPARATORS))
                )
        elif spec.kind == "threshold":
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                errors.append(f"{name} must be a non-negative integer")
        elif spec.kind == "scope":
            if value not in SCOPE_VALUES:
                errors.append(
                    f"{name} must be one of: " + ", ".join(SCOPE_VALUES)
                )
        elif spec.kind == "direction":
            if value not in DIRECTION_VALUES:
                errors.append(
                    f"{name} must be one of: " + ", ".join(DIRECTION_VALUES)
                )

    supports_label_scope = any(
        spec.kind == "label_set" for spec in template.slots.values()
    )
    selected_labels = {
        label
        for name, spec in template.slots.items()
        if spec.kind == "label_set"
        for label in (parameters.get(name) or [])
        if isinstance(label, str)
    }
    missing_labels = (
        required_labels - selected_labels
        if supports_label_scope
        else frozenset()
    )
    if missing_labels:
        errors.append(
            "routing omits explicitly enumerated labels: "
            + ", ".join(sorted(missing_labels))
            + "; include every required label even when absent from this drawing"
        )

    if category == "entity_lookup" and not errors:
        if not parameters.get("labels") and not parameters.get("tags"):
            errors.append("entity_lookup requires labels and/or tags")
    return errors


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _label_rules(head: str, labels: list[str]) -> list[str]:
    return [
        f"{head}(N) :- node_label(N, {_quote(label)})." for label in labels
    ]


def _program_header(include_dir: str) -> list[str]:
    return [
        f'.include "{include_dir}/graph_facts.dl"',
        f'.include "{include_dir}/graph_topology_semantics.dl"',
        ".decl result_witness(id:symbol)",
        ".output result_witness",
        "",
    ]


def render_program(
    routing: dict, include_dir: str = DEFAULT_INCLUDE_DIR
) -> str:
    """Render a validated routing JSON into an executable Datalog program.

    Callers must run :func:`validate_routing` first; this function assumes a
    valid binding and raises for the abstention category, which produces no
    program by design.
    """
    category = routing["category"]
    if category == "policy_abstention":
        raise ValueError(
            "policy_abstention renders no program; route to the mechanical "
            "abstention helper"
        )
    parameters = routing.get("parameters") or {}
    lines = _program_header(include_dir)

    if category == "entity_lookup":
        for label in parameters.get("labels") or []:
            lines.append(f"result_witness(N) :- node_label(N, {_quote(label)}).")
        for tag in parameters.get("tags") or []:
            lines.append(f"result_witness(N) :- node_tag(N, {_quote(tag)}).")
    elif category == "attachment":
        lines.append(".decl entity(id:symbol)")
        lines.extend(_label_rules("entity", parameters["entity_labels"]))
        roles = parameters.get("roles") or list(ATTACHMENT_ROLES)
        lines.append(".decl linked(id:symbol)")
        for role in roles:
            lines.append(
                f"linked(N) :- reference_edge(_, N, {_quote(role)})."
            )
            lines.append(
                f"linked(N) :- reference_edge(N, _, {_quote(role)})."
            )
        if parameters["mode"] == "attached":
            lines.append("result_witness(N) :- entity(N), linked(N).")
        else:
            lines.append("result_witness(N) :- entity(N), !linked(N).")
    elif category in ("reachability", "guarded_reachability"):
        lines.append(".decl src(id:symbol)")
        lines.extend(_label_rules("src", parameters["source_labels"]))
        lines.append(".decl tgt(id:symbol)")
        lines.extend(_label_rules("tgt", parameters["target_labels"]))
        lines.append(".decl hit(id:symbol)")
        scope = parameters.get("scope") or "piping"
        direction = parameters.get("direction") or "directed"
        reach_rel = {
            ("piping", "directed"): "piping_reachable",
            ("piping", "undirected"): "piping_connected",
            ("any", "directed"): "reachable_any",
            ("any", "undirected"): "reachable_any_undirected",
        }[(scope, direction)]
        lines.append(f"hit(N) :- tgt(N), src(S), {reach_rel}(S, N).")
        if category == "reachability":
            lines.append("result_witness(N) :- hit(N).")
        else:
            lines.append("result_witness(N) :- tgt(N), !hit(N).")
    elif category == "class_count":
        lines.append(".decl member(id:symbol)")
        lines.extend(_label_rules("member", parameters["labels"]))
        comparator = COUNT_COMPARATORS[parameters["comparator"]]
        threshold = parameters["threshold"]
        lines.append(".decl total(c:number)")
        lines.append("total(c) :- c = count : { member(_) }.")
        lines.append(
            "result_witness(N) :- member(N), total(c), "
            f"c {comparator} {threshold}."
        )
    else:  # pragma: no cover - pack and renderer kept in lockstep
        raise ValueError(f"no renderer for category {category!r}")

    return "\n".join(lines) + "\n"

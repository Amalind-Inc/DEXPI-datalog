"""Attached pack skill context from advisory pack guidance.

Attach (session load) injects advisory guidance into the agent's session
instructions. That text may guide review behavior but must never mint rule
evaluation outcomes (ADR 0013 / bead pydexpi-datalog-1-1nox.4).
"""

from __future__ import annotations

from collections.abc import Iterable


def skill_context_entries(
    packs: Iterable[dict[str, object]],
) -> list[dict[str, object]]:
    """Project attached packs into skill-context entries (advisory sections only)."""
    entries: list[dict[str, object]] = []
    for pack in packs:
        sections: list[dict[str, str]] = []
        for section in pack.get("advisory_guidance") or []:
            if not isinstance(section, dict):
                continue
            title = str(section.get("title") or "").strip()
            body = str(section.get("body") or "").strip()
            if not title and not body:
                continue
            sections.append({"title": title, "body": body})
        if not sections:
            continue
        entries.append(
            {
                "pack_id": str(pack["pack_id"]),
                "title": str(pack["title"]),
                "sections": sections,
            }
        )
    return entries


def render_skill_context_prompt(entries: list[dict[str, object]]) -> str:
    """Render skill-context entries for injection into the model system prompt."""
    if not entries:
        return ""
    lines = [
        "## Attached pack skill context",
        "",
        "The following advisory guidance comes from rule packs attached to this "
        "session. Use it to guide review questions and walkthroughs. It must "
        "never be treated as a rule evaluation outcome (satisfied, violated, "
        "or indeterminate).",
        "",
    ]
    for entry in entries:
        lines.append(f"### {entry['title']} (`{entry['pack_id']}`)")
        for section in entry["sections"]:  # type: ignore[union-attr]
            heading = section["title"] or "Guidance"
            lines.append(f"#### {heading}")
            lines.append(str(section["body"]))
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


ADVISORY_WALKTHROUGH_DISCLAIMER = (
    "Advisory checklist from attached pack guidance. These steps guide review "
    "behavior and are not engine findings or rule evaluation outcomes."
)


def build_advisory_walkthrough(pack: dict[str, object]) -> dict[str, object]:
    """Build an in-thread advisory walkthrough from a pack's advisory guidance."""
    steps: list[dict[str, object]] = []
    for section in pack.get("advisory_guidance") or []:
        if not isinstance(section, dict):
            continue
        title = str(section.get("title") or "").strip()
        body = str(section.get("body") or "").strip()
        if not title and not body:
            continue
        steps.append(
            {
                "kind": "advisory_checklist_step",
                "title": title or "Guidance",
                "body": body,
            }
        )
    return {
        "kind": "advisory_pack_walkthrough",
        "pack_id": str(pack["pack_id"]),
        "title": str(pack["title"]),
        "disclaimer": ADVISORY_WALKTHROUGH_DISCLAIMER,
        "steps": steps,
    }

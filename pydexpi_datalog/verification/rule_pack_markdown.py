"""Parse a rule pack authored as a canonical markdown document.

A rule pack IS a markdown file (bead pydexpi-datalog-1-1vd). The format:

- YAML frontmatter with pack metadata: ``pack_id``, ``version``, ``title``,
  ``authoritative``, ``trust_notice``.
- One ``##`` heading per rule, carrying the rule title and an explicit id
  anchor: ``## Pump discharge check valve {#pump_discharge_check_valve}``.
- The prose between the heading and the rule's fenced code block is the
  engineer-readable restatement (wrapped source lines are unwrapped per
  paragraph).
- One fenced ```` ```souffle-datalog ```` block per rule holding the exact
  Souffle program that is executed for the rule -- displayed logic and
  executed logic share this single source.

``parse_rule_pack_markdown`` returns the same structured pack shape the rest
of the system already consumes, plus a ``markdown`` key with the raw source
for document-style rendering.
"""

from __future__ import annotations

import re

import yaml


DEFAULT_OUTCOMES = ["satisfied", "violated", "indeterminate"]

_RULE_HEADING = re.compile(r"^##\s+(?P<title>.+?)\s*\{#(?P<rule_id>[A-Za-z0-9_.-]+)\}\s*$")
_FENCE = re.compile(r"^```(?P<language>[A-Za-z0-9_-]*)\s*$")

_FENCE_LANGUAGES = {
    "souffle-datalog": "souffle_datalog",
}


def parse_rule_pack_markdown(text: str) -> dict[str, object]:
    """Parse canonical rule-pack markdown into the structured pack shape."""
    metadata, body = _split_frontmatter(text)
    for key in ("pack_id", "version", "title", "authoritative", "trust_notice"):
        if key not in metadata:
            raise ValueError(f"rule pack markdown frontmatter is missing '{key}'")
    return {
        "pack_id": str(metadata["pack_id"]),
        "version": int(metadata["version"]),  # type: ignore[call-overload]
        "title": str(metadata["title"]),
        "authoritative": bool(metadata["authoritative"]),
        "trust_notice": str(metadata["trust_notice"]).strip(),
        "rules": _parse_rules(body),
        "markdown": text,
    }


def _split_frontmatter(text: str) -> tuple[dict[str, object], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("rule pack markdown must start with YAML frontmatter")
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            frontmatter = "\n".join(lines[1:index])
            body = "\n".join(lines[index + 1 :])
            metadata = yaml.safe_load(frontmatter)
            if not isinstance(metadata, dict):
                raise ValueError("rule pack frontmatter must be a YAML mapping")
            return metadata, body
    raise ValueError("rule pack markdown frontmatter is not terminated")


def _parse_rules(body: str) -> list[dict[str, object]]:
    rules: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    prose_lines: list[str] = []
    fence_language: str | None = None
    fence_lines: list[str] | None = None

    def finish_rule() -> None:
        nonlocal current, prose_lines
        if current is None:
            return
        if current.get("executable_logic") is None:
            raise ValueError(
                f"rule '{current['rule_id']}' has no fenced souffle-datalog block"
            )
        current["restatement"] = {
            "kind": "engineer_readable_rule_restatement",
            "plain_language_meaning": _unwrap_paragraphs(prose_lines),
        }
        rules.append(current)
        current = None
        prose_lines = []

    for line in body.splitlines():
        if fence_lines is not None:
            if line.strip() == "```":
                if current is None or fence_language is None:
                    raise ValueError("fenced block outside of a rule section")
                if current.get("executable_logic") is not None:
                    raise ValueError(
                        f"rule '{current['rule_id']}' has more than one fenced block"
                    )
                current["executable_logic"] = {
                    "kind": "collapsed_executable_logic",
                    "language": _FENCE_LANGUAGES.get(fence_language, fence_language),
                    "content": "\n".join(fence_lines) + "\n",
                    "inspectable": True,
                    "editable": False,
                    "disclosure": "collapsed",
                }
                fence_lines = None
                fence_language = None
            else:
                fence_lines.append(line)
            continue

        heading = _RULE_HEADING.match(line)
        if heading is not None:
            finish_rule()
            current = {
                "rule_id": heading.group("rule_id"),
                "title": heading.group("title"),
                "outcomes": list(DEFAULT_OUTCOMES),
                "restatement": None,
                "executable_logic": None,
            }
            continue

        fence = _FENCE.match(line)
        if fence is not None and current is not None:
            fence_language = fence.group("language")
            fence_lines = []
            continue

        if current is not None:
            prose_lines.append(line)

    if fence_lines is not None:
        raise ValueError("rule pack markdown ends inside a fenced block")
    finish_rule()

    if not rules:
        raise ValueError("rule pack markdown declares no rules")
    return rules


def _unwrap_paragraphs(lines: list[str]) -> str:
    """Join wrapped source lines per paragraph; keep paragraph breaks."""
    paragraphs: list[list[str]] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            if paragraphs and paragraphs[-1]:
                paragraphs.append([])
            continue
        if not paragraphs:
            paragraphs.append([])
        paragraphs[-1].append(line)
    return "\n\n".join(" ".join(part) for part in paragraphs if part)

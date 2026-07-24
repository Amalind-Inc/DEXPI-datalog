"""Parse a rule pack authored as a canonical markdown document.

A rule pack IS a markdown file (bead pydexpi-datalog-1-1vd, ADR 0013). The
format:

- YAML frontmatter with pack metadata: ``pack_id``, ``version``, ``title``,
  ``authoritative``, ``trust_notice``.
- Optional advisory pack guidance: ``##`` headings *without* a ``{#id}``
  anchor (plus leading overview prose under the pack ``#`` title).
- Zero or more executable rules: ``##`` headings *with* an explicit id
  anchor ``## Title {#rule_id}``, engineer-readable restatement prose, and
  exactly one fenced ```` ```souffle-datalog ```` block (displayed ==
  executed).

``parse_rule_pack_markdown`` returns the structured pack shape the rest of
the system consumes, including ``advisory_guidance`` and ``rules``, plus a
``markdown`` key with the raw source for document-style rendering.
"""

from __future__ import annotations

import re

import yaml


DEFAULT_OUTCOMES = ["satisfied", "violated", "indeterminate"]

_RULE_HEADING = re.compile(r"^##\s+(?P<title>.+?)\s*\{#(?P<rule_id>[A-Za-z0-9_.-]+)\}\s*$")
_ADVISORY_HEADING = re.compile(r"^##\s+(?P<title>.+?)\s*$")
_DOC_TITLE = re.compile(r"^#\s+(?P<title>.+?)\s*$")
_FENCE = re.compile(r"^```(?P<language>[A-Za-z0-9_-]*)\s*$")

_FENCE_LANGUAGES = {
    "souffle-datalog": "souffle_datalog",
}
_RULE_TRUST_COMMENT = re.compile(
    r"<!--\s*rule_trust:\s*(?P<trust>[A-Za-z0-9_-]+)\s*-->"
)


def parse_rule_pack_markdown(text: str) -> dict[str, object]:
    """Parse canonical rule-pack markdown into the structured pack shape."""
    metadata, body = _split_frontmatter(text)
    for key in ("pack_id", "version", "title", "authoritative", "trust_notice"):
        if key not in metadata:
            raise ValueError(f"rule pack markdown frontmatter is missing '{key}'")
    advisory_guidance, rules = _parse_body(body)
    return {
        "pack_id": str(metadata["pack_id"]),
        "version": int(metadata["version"]),  # type: ignore[call-overload]
        "title": str(metadata["title"]),
        "authoritative": bool(metadata["authoritative"]),
        "trust_notice": str(metadata["trust_notice"]).strip(),
        "advisory_guidance": advisory_guidance,
        "rules": rules,
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


def _parse_body(body: str) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    advisory: list[dict[str, object]] = []
    rules: list[dict[str, object]] = []

    mode: str | None = None  # "advisory" | "rule"
    section_title = ""
    prose_lines: list[str] = []
    current_rule: dict[str, object] | None = None
    fence_language: str | None = None
    fence_lines: list[str] | None = None
    saw_doc_title = False

    def finish_advisory() -> None:
        nonlocal mode, section_title, prose_lines
        body_text = _unwrap_paragraphs(prose_lines)
        if section_title or body_text:
            advisory.append(
                {
                    "kind": "advisory_pack_guidance",
                    "title": section_title,
                    "body": body_text,
                }
            )
        mode = None
        section_title = ""
        prose_lines = []

    def finish_rule() -> None:
        nonlocal mode, current_rule, prose_lines
        if current_rule is None:
            return
        if current_rule.get("executable_logic") is None:
            raise ValueError(
                f"rule '{current_rule['rule_id']}' has no fenced souffle-datalog block"
            )
        trust = "unspecified"
        cleaned_prose: list[str] = []
        for line in prose_lines:
            match = _RULE_TRUST_COMMENT.search(line)
            if match is not None:
                trust = match.group("trust")
                continue
            cleaned_prose.append(line)
        current_rule["trust"] = trust
        current_rule["restatement"] = {
            "kind": "engineer_readable_rule_restatement",
            "plain_language_meaning": _unwrap_paragraphs(cleaned_prose),
        }
        rules.append(current_rule)
        current_rule = None
        mode = None
        prose_lines = []

    def finish_current() -> None:
        if mode == "rule":
            finish_rule()
        elif mode == "advisory":
            finish_advisory()

    for line in body.splitlines():
        if fence_lines is not None:
            if line.strip() == "```":
                if current_rule is None or fence_language is None:
                    raise ValueError("fenced block outside of a rule section")
                if current_rule.get("executable_logic") is not None:
                    raise ValueError(
                        f"rule '{current_rule['rule_id']}' has more than one fenced block"
                    )
                current_rule["executable_logic"] = {
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

        rule_heading = _RULE_HEADING.match(line)
        if rule_heading is not None:
            finish_current()
            mode = "rule"
            current_rule = {
                "rule_id": rule_heading.group("rule_id"),
                "title": rule_heading.group("title"),
                "outcomes": list(DEFAULT_OUTCOMES),
                "restatement": None,
                "executable_logic": None,
            }
            prose_lines = []
            continue

        advisory_heading = _ADVISORY_HEADING.match(line)
        if advisory_heading is not None:
            finish_current()
            mode = "advisory"
            section_title = advisory_heading.group("title")
            prose_lines = []
            continue

        doc_title = _DOC_TITLE.match(line)
        if doc_title is not None and mode is None and not saw_doc_title:
            saw_doc_title = True
            # Leading overview prose after the pack H1 is advisory guidance.
            mode = "advisory"
            section_title = ""
            prose_lines = []
            continue

        fence = _FENCE.match(line)
        if fence is not None and mode == "rule":
            fence_language = fence.group("language")
            fence_lines = []
            continue

        if mode is None and line.strip():
            # Body prose before any heading becomes untitled overview advisory.
            mode = "advisory"
            section_title = ""
            prose_lines = [line]
            continue

        if mode is not None:
            prose_lines.append(line)

    if fence_lines is not None:
        raise ValueError("rule pack markdown ends inside a fenced block")
    finish_current()
    return advisory, rules


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

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkflowPolicy:
    max_source_files: int
    model_access: str
    source_node_selection: bool
    allowed_commands: frozenset[str]


OSS_POLICY = WorkflowPolicy(
    max_source_files=1,
    model_access="byok",
    source_node_selection=True,
    allowed_commands=frozenset(
        {
            "dry-run",
            "export-facts",
            "export-corpus",
            "derive-graph-semantics",
            "verify-suite",
            "verify-raw-fixture",
            "draft-logic-request",
        }
    ),
)


def count_manifest_source_files(input_block: object) -> int:
    if not isinstance(input_block, dict):
        return 0

    dexpi_xml = input_block.get("dexpi_xml")
    dexpi_xmls = input_block.get("dexpi_xmls")

    count = 1 if isinstance(dexpi_xml, str) and dexpi_xml.strip() else 0
    if isinstance(dexpi_xmls, list):
        count += len(dexpi_xmls)
    return count

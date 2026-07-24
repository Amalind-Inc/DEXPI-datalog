from __future__ import annotations

from pydexpi_datalog.qa.topology_tools import TopologyTools
from pydexpi_datalog.verification.pack_skill_context import (
    render_skill_context_prompt,
    skill_context_entries,
)

MINIMAL_TOPOLOGY = {
    "nodes": [],
    "edges": [],
    "evidence_map": {},
}


def test_skill_context_entries_project_advisory_sections_only() -> None:
    packs = [
        {
            "pack_id": "a",
            "title": "Pack A",
            "advisory_guidance": [
                {
                    "kind": "advisory_pack_guidance",
                    "title": "Isolation",
                    "body": "Check valves.",
                }
            ],
            "rules": [{"rule_id": "r1"}],
        },
        {
            "pack_id": "empty",
            "title": "Empty",
            "advisory_guidance": [],
            "rules": [],
        },
    ]
    entries = skill_context_entries(packs)
    assert [entry["pack_id"] for entry in entries] == ["a"]
    assert entries[0]["sections"][0]["title"] == "Isolation"


def test_topology_tools_system_prompt_includes_attached_skill_context() -> None:
    entries = skill_context_entries(
        [
            {
                "pack_id": "skill-pack-a",
                "title": "Skill Pack A",
                "advisory_guidance": [
                    {
                        "kind": "advisory_pack_guidance",
                        "title": "Isolation checklist",
                        "body": "Confirm isolation valves around major equipment.",
                    }
                ],
            }
        ]
    )
    tools = TopologyTools(
        topology_view=MINIMAL_TOPOLOGY,
        session_id="skill-context-test",
        attached_pack_skill_context=entries,
    )
    prompt = tools.system_prompt()
    assert "Attached pack skill context" in prompt
    assert "Isolation checklist" in prompt
    assert "never be treated as a rule evaluation outcome" in prompt
    assert render_skill_context_prompt(entries) in prompt

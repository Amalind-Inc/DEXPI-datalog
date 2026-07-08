from __future__ import annotations

import textwrap

from pydexpi_datalog.verification.bundled_rule_pack import bundled_rule_packs
from pydexpi_datalog.verification.rule_pack_markdown import parse_rule_pack_markdown
from pydexpi_datalog.verification.souffle_rule_pack import (
    load_diameter_rule_datalog,
    load_rule_datalog,
)


SAMPLE_PACK_MARKDOWN = textwrap.dedent(
    """\
    ---
    pack_id: sample-pack
    version: 3
    title: Sample checks
    authoritative: false
    trust_notice: Demonstration content only; not an authoritative standard.
    ---

    # Sample checks

    ## First rule title {#first_rule}

    If a thing exists, then another thing must be reachable
    from it before the boundary.

    ```souffle-datalog
    .decl first_rule(x: symbol)
    first_rule(x) :- thing(x).
    ```

    ## Second rule title {#second_rule}

    A line must declare a value in the loaded source.

    ```souffle-datalog
    .decl second_rule(x: symbol)
    second_rule(x) :- line(x).
    ```
    """
)


def test_parse_markdown_produces_structured_pack_shape() -> None:
    pack = parse_rule_pack_markdown(SAMPLE_PACK_MARKDOWN)

    assert pack["pack_id"] == "sample-pack"
    assert pack["version"] == 3
    assert pack["title"] == "Sample checks"
    assert pack["authoritative"] is False
    assert "not an authoritative" in str(pack["trust_notice"])
    # The raw markdown source travels with the pack (detail-page raw view).
    assert pack["markdown"] == SAMPLE_PACK_MARKDOWN

    rules = pack["rules"]
    assert [rule["rule_id"] for rule in rules] == ["first_rule", "second_rule"]
    first = rules[0]
    assert first["title"] == "First rule title"
    assert first["outcomes"] == ["satisfied", "violated", "indeterminate"]
    assert first["restatement"]["kind"] == "engineer_readable_rule_restatement"
    assert first["restatement"]["plain_language_meaning"].startswith(
        "If a thing exists,"
    )
    # Prose keeps its meaning as one paragraph even when wrapped in the source.
    assert "reachable from it" in first["restatement"]["plain_language_meaning"]

    logic = first["executable_logic"]
    assert logic["kind"] == "collapsed_executable_logic"
    assert logic["language"] == "souffle_datalog"
    assert logic["content"] == ".decl first_rule(x: symbol)\nfirst_rule(x) :- thing(x).\n"
    assert logic["inspectable"] is True
    assert logic["editable"] is False
    assert logic["disclosure"] == "collapsed"


def test_bundled_demo_pack_is_parsed_from_markdown_source() -> None:
    packs = bundled_rule_packs()
    demo = next(pack for pack in packs if pack["pack_id"] == "demo-process-safety")

    markdown = demo["markdown"]
    assert isinstance(markdown, str)
    assert "pump_discharge_check_valve" in markdown
    assert "discharge_line_min_diameter" in markdown
    assert "```souffle-datalog" in markdown


def test_executable_logic_and_displayed_logic_share_one_markdown_source() -> None:
    packs = bundled_rule_packs()
    demo = next(pack for pack in packs if pack["pack_id"] == "demo-process-safety")
    by_id = {rule["rule_id"]: rule for rule in demo["rules"]}

    # The Souffle program actually executed is the fenced block from the
    # markdown pack -- displayed logic can never drift from executed logic.
    assert by_id["pump_discharge_check_valve"]["executable_logic"]["content"] == (
        load_rule_datalog()
    )
    assert by_id["discharge_line_min_diameter"]["executable_logic"]["content"] == (
        load_diameter_rule_datalog()
    )

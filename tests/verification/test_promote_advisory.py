from __future__ import annotations

from pydexpi_datalog.verification.promote_advisory import (
    classify_expressible_island,
    propose_advisory_promotion,
)


def test_component_presence_clause_is_in_island() -> None:
    assert (
        classify_expressible_island(
            "The prepared diagram must include at least one CentrifugalPump."
        )
        == "in_island"
    )


def test_adequacy_judgment_clause_is_outside_island() -> None:
    assert (
        classify_expressible_island(
            "Relief capacity must be adequate for the worst-case fire scenario."
        )
        == "outside_island"
    )


def test_propose_promotion_builds_reviewable_draft() -> None:
    pack = {
        "pack_id": "p",
        "advisory_guidance": [
            {
                "kind": "advisory_pack_guidance",
                "title": "Pump presence",
                "body": "The prepared diagram must include at least one CentrifugalPump.",
            }
        ],
    }
    proposal = propose_advisory_promotion(pack=pack, advisory_title="Pump presence")
    assert proposal["status"] == "draft"
    draft = proposal["draft"]
    assert draft["trust"] == "pending_author_confirmation"
    assert draft["executable_logic"]["disclosure"] == "collapsed"
    assert ".decl rule_result" in draft["executable_logic"]["content"]
    assert "CentrifugalPump" in draft["restatement"]["plain_language_meaning"]

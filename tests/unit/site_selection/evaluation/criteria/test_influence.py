"""The anthropic influence criterion reads the major-influence flags of a basin."""

from __future__ import annotations

import pytest

from hydromodpy.spatial.site_selection.config import InfluenceCriteriaConfig
from hydromodpy.spatial.site_selection.evaluation.criteria.influence import (
    evaluate_influence_criterion,
)

pytestmark = pytest.mark.fast

REJECT_DAMS = {"reject_major_dam_upstream": True}


def _influence(mode: str, attributes: dict, **checks):
    return evaluate_influence_criterion(
        site_id="site_001",
        attributes=attributes,
        config=InfluenceCriteriaConfig(mode=mode, **checks),
        selection_principle="observation_led",
        evaluation_order=2,
    )


@pytest.mark.parametrize(
    ("mode", "attributes", "checks", "status", "blocking", "reason"),
    [
        ("hard_reject", {"major_dam_upstream": "true"}, REJECT_DAMS, "failed", True,
         "rejection flags present: major_dam_upstream"),
        ("warning", {"has_major_dam_upstream": True}, REJECT_DAMS, "warning", False,
         "rejection flags present"),
        ("hard_reject", {"major_dam_upstream": "false"}, REJECT_DAMS, "passed", False,
         "no configured influence rejection flag"),
        ("hard_reject", {"dam_upstream": "true"}, {}, "passed", False, "no configured influence"),
        ("hard_reject", {}, REJECT_DAMS, "missing", False, "no configured influence"),
        ("report_only", {"regulated_reach": "non"}, {}, "reported", False,
         "without automatic decision"),
        ("report_only", {}, {}, "missing", False, "without automatic decision"),
    ],
)  # fmt: skip
def test_the_influence_criterion_follows_its_mode(
    mode, attributes, checks, status, blocking, reason
):
    component = _influence(mode, attributes, **checks)

    assert component.criterion_id == "influence"
    assert (component.criterion_status, component.blocking) == (status, blocking)
    assert reason in component.reason


@pytest.mark.parametrize(
    ("refs", "expected"),
    [
        ({"major_dam_upstream_evidence_refs": ["dam:1", "dam:1", "", "dam:2"]}, ["dam:1", "dam:2"]),
        ({"major_dam_upstream_evidence_refs": [], "influence_evidence_refs": "all:1"}, ["all:1"]),
        ({"influence_evidence_refs": 7}, ["7"]),
        ({"influence_evidence_refs": ""}, []),
    ],
)
def test_a_rejection_cites_the_evidence_of_its_own_flag_first(refs, expected):
    component = _influence("hard_reject", {"major_dam_upstream": "1", **refs}, **REJECT_DAMS)

    assert component.evidence_json["evidence_refs"] == expected
    assert component.evidence_json["evidence_ref"] == (expected[0] if expected else None)

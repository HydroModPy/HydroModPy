"""The lineage block links by ids, names its kind, and refuses what it does not know."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from hydromodpy.results.lineage import Lineage


def test_an_empty_lineage_is_a_first_run():
    lineage = Lineage()
    assert lineage.parent_sim_id is None
    assert lineage.kind is None
    assert lineage.overrides == {}


def test_a_lineage_round_trips_through_json():
    lineage = Lineage(
        parent_sim_id="9a4f" * 8,
        kind="version",
        overrides={"flow.param.K.field.value": 2e-5},
        parent_hint="runs/nancon_monthly",
    )
    assert (
        Lineage.model_validate(json.loads(json.dumps(lineage.model_dump(mode="json")))) == lineage
    )


def test_a_promoted_run_names_its_session_phase_and_trial():
    lineage = Lineage(session_id="sess", phase="transient_sy", trial=7, kind="promoted")
    assert (lineage.session_id, lineage.phase, lineage.trial) == ("sess", "transient_sy", 7)


def test_an_unknown_kind_is_refused_with_the_known_ones():
    with pytest.raises(ValidationError, match="rerun"):
        Lineage(kind="copy")


def test_a_trial_below_one_is_refused():
    with pytest.raises(ValidationError, match="trial"):
        Lineage(trial=0)


def test_an_unknown_key_is_refused_by_name():
    with pytest.raises(ValidationError, match="parent_name"):
        Lineage.model_validate({"parent_name": "nancon"})

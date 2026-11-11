"""The lineage block links by ids, names its kind, and refuses what it does not know."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from hydromodpy.schema.lineage import Lineage, Replay


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


@pytest.mark.parametrize("kind", ["rerun", "promoted", "trial", "version", "replay"])
def test_the_known_kinds_are_accepted(kind):
    assert Lineage(kind=kind).kind == kind


def test_published_is_no_lineage_kind():
    with pytest.raises(ValidationError, match="published"):
        Lineage(kind="published")


def test_a_seal_written_with_the_word_published_still_reads():
    from hydromodpy.core.config_kit.stored import dump_stored, read_stored

    lineage = read_stored(Lineage, {"kind": "published"})

    assert lineage.kind == "published"
    assert dump_stored(lineage)["kind"] == "published"


def test_a_replay_round_trips_under_the_word_class():
    replay = Replay(
        of="9a4f" * 8,
        source="run",
        source_version="2.0.0",
        basis="float64",
        class_="deviation",
        strict=True,
        differs={"fields/heads": {"max_abs": 1e-4, "rel_l2": 2e-6, "precision": "exact"}},
        added=["fields/new"],
        changes=["a_moved_default"],
    )
    lineage = Lineage(parent_sim_id=replay.of, kind="replay", replay=replay)

    stored = json.loads(json.dumps(lineage.model_dump(mode="json", by_alias=True)))
    read = Lineage.model_validate(stored)

    assert stored["replay"]["class"] == "deviation"
    assert "class_" not in stored["replay"]
    assert read.replay is not None
    assert read.replay.class_ == "deviation"
    assert read.replay.differs["fields/heads"].max_abs == 1e-4
    assert read.replay.strict is True


def test_a_replay_without_a_basis_has_no_class():
    with pytest.raises(ValidationError, match="class"):
        Replay(of="s", source="copy", source_version="2.0.0", basis="none", class_="bit")


def test_a_replay_with_a_basis_states_a_class():
    with pytest.raises(ValidationError, match="class"):
        Replay(of="s", source="run", source_version="2.0.0", basis="float64")


def test_the_vocabulary_refuses_a_class_this_code_does_not_measure():
    with pytest.raises(ValidationError, match="tolerance"):
        Replay(
            of="s",
            source="run",
            source_version="2.0.0",
            basis="float64",
            class_="tolerance",
        )
    with pytest.raises(ValidationError, match="archive"):
        Replay(of="s", source="archive", source_version="2.0.0", basis="float64", class_="bit")
    with pytest.raises(ValidationError, match="mixed"):
        Replay(of="s", source="run", source_version="2.0.0", basis="mixed", class_="bit")

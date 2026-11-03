"""The session and phase descriptors are written whole and read back typed."""

from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from hydromodpy.results.metric_rule import PeriodWindow
from hydromodpy.results.session.descriptor import (
    SESSION_SCHEMA,
    BestCase,
    BestTrial,
    ParameterBound,
    ScoredSamples,
    SessionCase,
    SessionDescriptor,
    read_session,
    scored_samples_text,
    session_descriptor_path,
    write_session,
)
from hydromodpy.results.session.phase import (
    PhaseDescriptor,
    list_phases,
    phase_dir,
    read_phase,
    write_phase,
)
from hydromodpy.results.storage.contract import SESSION_DESCRIPTOR_FILENAME, SESSION_PHASES_DIRNAME
from tests._helpers.session_documents import (
    NOW,
    best_trial,
    calibration_window,
    joint_session,
    session_descriptor,
)

WINDOWS = calibration_window(date(2016, 1, 1), date(2018, 12, 31))


def test_a_descriptor_round_trips_and_names_its_schema(tmp_path):
    descriptor = session_descriptor(
        "J0014010-calage",
        site="J0014010",
        status="completed",
        ended_at=NOW,
        windows=WINDOWS,
        bounds={"K": ParameterBound(lower=1e-7, upper=1e-4, search_space="log")},
        best=best_trial(
            7, cost=-0.84, sim_id="9a4f" * 8, rel_dir="runs/J0014010-calage", parameters={"K": 2e-5}
        ),
    )
    write_session(tmp_path, descriptor)

    assert read_session(tmp_path) == descriptor
    text = session_descriptor_path(tmp_path).read_text(encoding="utf-8")
    assert text.startswith('{\n  "schema": "hydromodpy.session.v4"')
    assert SESSION_SCHEMA == "hydromodpy.session.v4"
    assert '"site": "J0014010"' in text


def test_a_fresh_descriptor_is_running_without_a_best():
    descriptor = session_descriptor()
    assert (
        descriptor.status == "running" and descriptor.best is None and descriptor.ended_at is None
    )


def test_the_descriptor_is_rewritten_whole_and_flushed(tmp_path, monkeypatch):
    synced: list[int] = []
    real_fsync = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (synced.append(fd), real_fsync(fd)))
    write_session(tmp_path, session_descriptor())
    write_session(
        tmp_path,
        session_descriptor(status="aborted", ended_at=NOW, best=best_trial(4)),
    )

    assert read_session(tmp_path).status == "aborted"
    assert read_session(tmp_path).best.trial == 4
    assert [p.name for p in tmp_path.iterdir()] == [SESSION_DESCRIPTOR_FILENAME]
    assert len(synced) == 4


def test_a_running_session_cannot_have_ended():
    with pytest.raises(ValidationError, match="running session has no ended_at"):
        session_descriptor(ended_at=NOW)


def test_another_schema_or_an_unknown_key_is_refused_by_name():
    with pytest.raises(ValidationError, match=SESSION_SCHEMA):
        SessionDescriptor.model_validate(
            {**session_descriptor().model_dump(by_alias=True), "schema": "hydromodpy.session.v3"}
        )
    with pytest.raises(ValidationError, match="best_trial"):
        SessionDescriptor.model_validate(
            {**session_descriptor().model_dump(by_alias=True), "best_trial": 3}
        )


def test_a_session_of_one_case_names_its_case_its_site_and_its_run():
    descriptor = session_descriptor(
        "c", site="S1", best=best_trial(2, case="c", sim_id="x" * 32, rel_dir="runs/c")
    )
    assert (descriptor.only_case, descriptor.only_site) == ("c", "S1")
    assert descriptor.only_run == BestCase(sim_id="x" * 32, rel_dir="runs/c", cost=0.5)
    assert session_descriptor("c").only_run is None


def test_a_session_of_several_cases_names_no_single_case_site_or_run():
    descriptor = joint_session(
        best=BestTrial(trial=1, cost=0.4, cases={"a": BestCase(cost=0.3), "b": BestCase(cost=0.5)})
    )
    assert (descriptor.only_case, descriptor.only_site, descriptor.only_run) == (None, None, None)
    assert descriptor.windows["calibration"].of("a").end == date(2014, 12, 31)


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"cases": {}, "sites": []}, "at least one case"),
        ({"sites": ["S1"]}, r"sites are \['S1'\], the cases name \['S1', 'S2'\]"),
        (
            {
                "windows": {
                    "calibration": PeriodWindow(
                        role="calibration",
                        start=date(2010, 1, 1),
                        end=date(2012, 12, 31),
                        by_case={"a": {"start": date(2010, 1, 1), "end": date(2011, 12, 31)}},
                    )
                }
            },
            "by_case names every case or none",
        ),
    ],
    ids=["no_case", "wrong_sites", "partial_window"],
)
def test_a_session_whose_tables_disagree_is_refused_at_writing(fields, message):
    with pytest.raises(ValidationError, match=message):
        joint_session(**fields)


def _document(**changes) -> dict:
    return {
        **session_descriptor(best=best_trial(1)).model_dump(mode="json", by_alias=True),
        **changes,
    }


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"config_hash": "other"}, "different config hashes"),
        (
            {"best": {**_document()["best"], "cost": 0.9}},
            "different costs",
        ),
    ],
    ids=["config_hash", "best_cost"],
)
def test_a_case_that_says_other_than_its_session_is_refused_at_writing_only(
    tmp_path, changes, message
):
    with pytest.raises(ValidationError, match=message):
        SessionDescriptor.model_validate(_document(**changes))
    session_descriptor_path(tmp_path).write_text(json.dumps(_document(**changes)), encoding="utf-8")
    assert read_session(tmp_path).case_id == "case"


def test_phase_descriptors_live_under_phases_and_list_by_index(tmp_path):
    second = PhaseDescriptor(
        phase_id="p2",
        name="transient_sy",
        index=1,
        status="running",
        frozen={
            "K": {
                "value": 6.1e-6,
                "targets": {"case": "flow.hk"},
                "mode": "replace",
                "from_phase": "steady_k",
            }
        },
        restarts=1,
        cost_name="nse_log",
        windows=WINDOWS,
    )
    first = PhaseDescriptor(
        phase_id="p1", name="steady_k", index=0, status="completed", best=best_trial(3, cost=0.2)
    )
    write_phase(tmp_path, second)
    write_phase(tmp_path, first)

    assert phase_dir(tmp_path, "steady_k") == tmp_path / SESSION_PHASES_DIRNAME / "steady_k"
    assert read_phase(tmp_path, "transient_sy") == second
    assert read_phase(tmp_path, "transient_sy").frozen["K"].from_phase == "steady_k"
    assert [phase.name for phase in list_phases(tmp_path)] == ["steady_k", "transient_sy"]
    assert list_phases(tmp_path / "elsewhere") == []


def test_a_phase_name_is_a_directory_name():
    with pytest.raises(ValidationError, match="name"):
        PhaseDescriptor(phase_id="p", name="steady k", index=0)


def test_the_descriptor_carries_the_periods_it_scored_its_cost_on(tmp_path):
    write_session(tmp_path, session_descriptor(windows=WINDOWS))
    period = read_session(tmp_path).windows["calibration"]
    assert (period.role, period.start, period.end) == (
        "calibration",
        date(2016, 1, 1),
        date(2018, 12, 31),
    )
    assert session_descriptor().windows == {}


@pytest.mark.parametrize("rel_dir", ["/abs/runs/x", "runs/../x", "share/x"])
def test_a_best_trial_rel_dir_follows_the_one_grammar(rel_dir):
    with pytest.raises(ValidationError, match="not a result directory"):
        BestCase(rel_dir=rel_dir)
    assert BestCase(rel_dir="sessions/c/trials/0001/case").rel_dir == "sessions/c/trials/0001/case"


def test_the_pairs_a_cost_was_scored_on_read_in_words():
    scored = [
        ScoredSamples(window="calibration", case_id="a", output="discharge", n=120),
        ScoredSamples(
            window="calibration",
            case_id="a",
            output="head",
            n=40,
            n_sim_nan=3,
            first=date(2016, 1, 31),
            last=date(2018, 12, 31),
        ),
    ]
    assert scored_samples_text(scored) == (
        "discharge 120 pair(s); head 40 pair(s) (3 lost to a NaN simulated value), "
        "period ends 2016-01-31 to 2018-12-31"
    )
    assert scored_samples_text(iter(scored[:1])) == "discharge 120 pair(s)"
    assert scored_samples_text([]) == ""

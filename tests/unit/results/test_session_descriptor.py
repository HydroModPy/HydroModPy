"""The session and phase descriptors are written whole and read back typed."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from hydromodpy.results.metric_rule import PeriodWindow
from hydromodpy.results.session.descriptor import (
    SESSION_SCHEMA,
    SessionCase,
    SessionDescriptor,
    read_session,
    session_descriptor_path,
)
from tests._helpers.session_documents import (
    NOW,
    best_trial,
    calibration_window,
    joint_session,
    session_descriptor,
)

WINDOWS = calibration_window(date(2016, 1, 1), date(2018, 12, 31))


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

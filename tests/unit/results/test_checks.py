"""The checks block seals facts, flattens to the declared columns, and refuses what it does not know."""

from __future__ import annotations

import json
from datetime import date

import pytest
from pydantic import ValidationError

from hydromodpy.results.checks import CHECKS_SCHEMA, CalibratedBy, Checks, Validity
from hydromodpy.results.metric_rule import DateWindow
from hydromodpy.results.storage.parquet_schemas import CHECK_COLUMNS
from tests.unit.results._run_record_factory import make_checks


def test_a_block_round_trips_through_json():
    checks = make_checks(
        validities=[
            Validity("water_budget", False, 12.0, "does not close", True),
            Validity("coverage", True, 0.97, "enough observations"),
        ],
        bounds_hit=["K"],
    )
    text = json.dumps(checks.model_dump(mode="json"))

    assert Checks.model_validate(json.loads(text)) == checks
    assert isinstance(Checks.model_validate(json.loads(text)).validities[0], Validity)


def test_flatten_gives_exactly_the_declared_columns_in_order():
    assert tuple(make_checks().flatten()) == CHECK_COLUMNS


def test_flatten_names_the_failed_validities_and_the_bounds():
    checks = make_checks(
        validities=[
            Validity("water_budget", False, 12.0, "does not close", True),
            Validity("coverage", False, 0.3, "too few observations"),
            Validity("convergence", True, None, "converged"),
        ],
        bounds_hit=["K", "Sy"],
    )
    flat = checks.flatten()

    assert flat["validities_failed"] == "water_budget,coverage"
    assert flat["fatal_failed"] is True
    assert flat["bounds_hit"] == "K,Sy"
    assert flat["calibrated_by_session_status"] == "completed"
    assert str(flat["score_window_start"]) == "2016-01-01"


def test_an_empty_block_flattens_to_nulls_and_no_fatal_failure():
    flat = Checks().flatten()
    assert flat["validities_failed"] is None
    assert flat["bounds_hit"] is None
    assert flat["fatal_failed"] is False
    assert flat["calibrated_by_session_id"] is None


def test_fatal_failed_ignores_a_non_fatal_failure():
    checks = Checks(validities=[Validity("coverage", False, 0.3, "too few", False)])
    assert checks.failed_validities() == (checks.validities[0],)
    assert checks.fatal_failed() is False


def test_the_session_status_is_one_of_three_words():
    with pytest.raises(ValidationError, match="session_status"):
        CalibratedBy(session_id="s", trial=1, session_status="running")


def test_an_unknown_key_is_refused_by_name():
    with pytest.raises(ValidationError, match="validity"):
        Checks.model_validate({"validity": "ok"})


def test_the_block_has_a_schema_id_for_its_json_schema_file():
    assert CHECKS_SCHEMA == "hydromodpy.checks.v1"
    assert "validities" in Checks.model_json_schema()["properties"]


def test_the_calibration_window_flattens_next_to_the_session():
    window = DateWindow(start=date(2016, 1, 1), end=date(2018, 12, 31))
    by = CalibratedBy(session_id="s", trial=1, session_status="completed", window=window)
    flat = make_checks(calibrated_by=by).flatten()
    assert flat["calibrated_by_window_start"] == date(2016, 1, 1)
    assert flat["calibrated_by_window_end"] == date(2018, 12, 31)
    assert make_checks().flatten()["calibrated_by_window_start"] is None

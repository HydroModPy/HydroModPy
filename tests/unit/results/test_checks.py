"""The checks block seals facts, flattens to the declared columns, and refuses what it does not know."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.results.record.checks import CHECKS_SCHEMA, Checks


def test_the_block_has_a_schema_id_for_its_json_schema_file():
    assert CHECKS_SCHEMA == "hydromodpy.checks.v2"
    assert Checks().schema_ == CHECKS_SCHEMA
    assert Checks.model_validate({"schema": CHECKS_SCHEMA}).schema_ == CHECKS_SCHEMA
    assert "validities" in Checks.model_json_schema()["properties"]


def test_a_block_of_another_schema_is_refused_by_name():
    with pytest.raises(ValidationError, match="hydromodpy.checks.v1"):
        Checks.model_validate({"schema": "hydromodpy.checks.v1"})

"""The checks block of a run record, with its schema id.

It seals facts, flattens them to the declared columns and refuses a block of
another schema.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.results.record.checks import CHECKS_SCHEMA, Checks


def test_schema_id() -> None:
    assert CHECKS_SCHEMA == "hydromodpy.checks.v2"
    assert Checks().schema_ == CHECKS_SCHEMA
    assert Checks.model_validate({"schema": CHECKS_SCHEMA}).schema_ == CHECKS_SCHEMA
    assert "validities" in Checks.model_json_schema()["properties"]


def test_refusals() -> None:
    with pytest.raises(ValidationError, match="hydromodpy.checks.v1"):
        Checks.model_validate({"schema": "hydromodpy.checks.v1"})

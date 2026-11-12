"""One scalar of a TOML file, a number or a text like ``"12.3 m"``, split into its value and its unit.

A bare number takes the unit of its field. A text that carries no number, a
boolean and a list are refused.
"""

from __future__ import annotations

import pytest

from hydromodpy.core.units.scalar import parse_scalar_and_unit

SCALAR_REFUSALS = [
    pytest.param(
        {"value": 1.0, "explicit_unit": "  "},
        ValueError,
        "has an empty explicit unit",
        id="empty explicit unit",
    ),
    pytest.param(
        {"value": 1.0, "default_unit": " "},
        ValueError,
        "requires a non-empty default_unit",
        id="empty default unit",
    ),
    pytest.param({"value": True}, TypeError, "must be numeric", id="boolean"),
    pytest.param({"value": "  "}, ValueError, "cannot be an empty string", id="blank text"),
    pytest.param({"value": [1.0]}, TypeError, "must be numeric", id="list"),
]


@pytest.mark.parametrize(("arguments", "error", "message"), SCALAR_REFUSALS)
def test_refusals(arguments, error, message) -> None:
    arguments = {"default_unit": "m"} | arguments
    with pytest.raises(error, match=message):
        parse_scalar_and_unit(location="x", **arguments)

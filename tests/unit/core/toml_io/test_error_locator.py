"""A pydantic error found in a TOML file points back to the line the user wrote."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ValidationError

from hydromodpy.core.toml_io.error_locator import (
    format_validation_error,
    locate_loc,
    resolve_loc,
    validation_error_details,
)

_TEXT = """\
title = "demo"

[flow]
k = "oops"   # not a number
ss = 1e-5

[[flow.layers]]
thickness = 2.0

[[flow.layers]]
thickness = "bad"

[other]
k = 3
"""


class _Layer(BaseModel):
    thickness: float


class _Flow(BaseModel):
    k: float
    ss: float
    layers: list[_Layer]


class _Doc(BaseModel):
    title: str
    flow: _Flow


def _error() -> ValidationError:
    try:
        _Doc.model_validate(
            {
                "title": "demo",
                "flow": {
                    "k": "oops",
                    "ss": 1e-5,
                    "layers": [{"thickness": 2.0}, {"thickness": "bad"}],
                },
            }
        )
    except ValidationError as exc:
        return exc
    raise AssertionError("expected a validation error")


def test_resolve_loc_follows_a_list_index():
    document = {"layers": [{"t": 1}]}
    assert resolve_loc(("layers", 0, "t"), document) == ("layers", "0", "t")
    assert resolve_loc(("layers", 5, "t"), document) == ("layers", "5", "t")
    assert resolve_loc(("s", "x"), {"s": "text"}) == ("s", "x")


def test_message_without_source(tmp_path: Path):
    message = format_validation_error(_error(), source_path=tmp_path / "gone.toml")
    assert "flow.k:" in message


def test_details_without_source(tmp_path: Path):
    details = validation_error_details(_error(), source_path=tmp_path / "gone.toml")
    assert all("line" not in record for record in details)


def test_locate_loc_finds_a_quoted_key():
    text = (
        "[sites.bind]\n"
        '"site.name" = "site"\n'
        "'geographic.catchment.x_outlet' = \"x_outlet\"\n"
        'plain = "p"\n'
    )
    assert locate_loc(text, ("sites", "bind", "site.name")) == 2
    assert locate_loc(text, ("sites", "bind", "geographic.catchment.x_outlet")) == 3
    assert locate_loc(text, ("sites", "bind", "plain")) == 4

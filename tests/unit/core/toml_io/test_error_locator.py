"""A pydantic error found in a TOML file points back to the line the user wrote."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ValidationError

from hydromodpy.core.toml_io.error_locator import (
    format_validation_error,
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


def test_a_list_index_is_followed_inside_the_document() -> None:
    document = {"layers": [{"t": 1}]}
    assert resolve_loc(("layers", 0, "t"), document) == ("layers", "0", "t")
    assert resolve_loc(("layers", 5, "t"), document) == ("layers", "5", "t")
    assert resolve_loc(("s", "x"), {"s": "text"}) == ("s", "x")


def test_a_source_that_cannot_be_read_still_gives_a_message(tmp_path: Path) -> None:
    message = format_validation_error(_error(), source_path=tmp_path / "gone.toml")
    assert "flow.k:" in message


def test_the_details_have_no_line_when_the_text_is_unavailable(tmp_path: Path) -> None:
    details = validation_error_details(_error(), source_path=tmp_path / "gone.toml")
    assert all("line" not in record for record in details)

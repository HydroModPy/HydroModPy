"""A pydantic error found in a TOML file points back to the line the user wrote."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from hydromodpy.core.toml_io.error_locator import (
    format_loc,
    format_validation_error,
    json_pointer,
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


@pytest.mark.parametrize(
    ("loc", "line"),
    [
        (("title",), 1),
        (("flow", "k"), 4),
        (("flow", "ss"), 5),
        (("flow", "layers", 0, "thickness"), 8),
        (("flow", "layers", 0), 7),
        (("flow", "missing"), 3),
        (("unknown", "key"), None),
        ((), None),
    ],
)
def test_a_loc_maps_to_the_line_of_its_key_or_the_closest_section(loc, line) -> None:
    assert locate_loc(_TEXT, loc) == line


def test_a_key_of_another_section_is_not_taken_for_the_one_asked() -> None:
    assert locate_loc(_TEXT, ("flow", "title")) == 3
    assert locate_loc(_TEXT, ("other", "k")) == 14


@pytest.mark.parametrize(
    ("loc", "expected"),
    [
        (("flow", "layers", 0, "kind"), "flow.layers[0].kind"),
        ((), ""),
        (("a",), "a"),
    ],
)
def test_a_loc_is_written_as_a_dotted_path(loc, expected) -> None:
    assert format_loc(loc) == expected


@pytest.mark.parametrize(
    ("loc", "expected"),
    [
        (("flow", "layers", 0, "kind"), "/flow/layers/0/kind"),
        ((), ""),
        (("a/b", "c~d"), "/a~1b/c~0d"),
    ],
)
def test_a_loc_is_written_as_a_json_pointer(loc, expected) -> None:
    assert json_pointer(loc) == expected


def test_a_variant_name_the_document_lacks_is_dropped_from_the_loc() -> None:
    document = {"flow": {"ic": {"type": "spinup_cyclic", "max_cycles": "x"}}}
    loc = ("flow", "ic", "spinup_cyclic", "max_cycles")
    assert resolve_loc(loc, document) == ("flow", "ic", "max_cycles")


def test_a_missing_key_is_kept_so_the_pointer_says_where_it_belongs() -> None:
    assert resolve_loc(("flow", "k"), {"flow": {}}) == ("flow", "k")


def test_a_list_index_is_followed_inside_the_document() -> None:
    document = {"layers": [{"t": 1}]}
    assert resolve_loc(("layers", 0, "t"), document) == ("layers", "0", "t")
    assert resolve_loc(("layers", 5, "t"), document) == ("layers", "5", "t")
    assert resolve_loc(("s", "x"), {"s": "text"}) == ("s", "x")


def test_an_error_in_the_second_block_of_an_array_of_tables_points_at_that_block() -> None:
    assert locate_loc(_TEXT, ("flow", "layers", 1, "thickness")) == 11
    assert locate_loc(_TEXT, ("flow", "layers", 0, "thickness")) == 8
    assert locate_loc(_TEXT, ("flow", "layers", 1)) == 10


def test_a_list_index_past_the_blocks_written_points_at_the_last_block() -> None:
    assert locate_loc(_TEXT, ("flow", "layers", 7)) == 10


def test_the_message_names_the_file_line_field_and_refused_value(tmp_path: Path) -> None:
    path = tmp_path / "p.toml"
    path.write_text(_TEXT, encoding="utf-8")
    message = format_validation_error(_error(), source_path=path)
    assert message.splitlines()[0] == f"2 validation error(s) in {path}:"
    assert f"{path}:4: flow.k:" in message
    assert "(input='oops')" in message
    assert "flow.layers[1].thickness:" in message


def test_the_message_without_a_source_has_no_line_number() -> None:
    message = format_validation_error(_error())
    assert "<config>: flow.k:" in message
    assert "<config>:4" not in message


def test_a_source_that_cannot_be_read_still_gives_a_message(tmp_path: Path) -> None:
    message = format_validation_error(_error(), source_path=tmp_path / "gone.toml")
    assert "flow.k:" in message


def test_a_long_input_is_left_out_of_the_message() -> None:
    class _M(BaseModel):
        x: int

    with pytest.raises(ValidationError) as caught:
        _M.model_validate({"x": "y" * 500})
    assert "(input=" not in format_validation_error(caught.value)


def test_a_prefix_puts_a_sub_mapping_error_back_where_the_user_wrote_it() -> None:
    with pytest.raises(ValidationError) as caught:
        _Flow.model_validate({"k": "oops", "ss": 1, "layers": []})
    message = format_validation_error(caught.value, text=_TEXT, loc_prefix=("flow",))
    assert "<config>:4: flow.k:" in message


def test_the_details_carry_pointer_loc_type_and_line() -> None:
    details = validation_error_details(_error(), text=_TEXT)
    first = details[0]
    assert first["pointer"] == "/flow/k"
    assert first["loc"] == "flow.k"
    assert first["type"] == "float_parsing"
    assert first["line"] == 4
    assert details[1]["pointer"] == "/flow/layers/1/thickness"


def test_the_details_have_no_line_when_the_text_is_unavailable(tmp_path: Path) -> None:
    details = validation_error_details(_error(), source_path=tmp_path / "gone.toml")
    assert all("line" not in record for record in details)


def test_the_details_read_the_file_when_given_a_path(tmp_path: Path) -> None:
    path = tmp_path / "p.toml"
    path.write_text(_TEXT, encoding="utf-8")
    assert validation_error_details(_error(), source_path=path)[0]["line"] == 4


def test_an_error_at_the_root_is_called_root() -> None:
    with pytest.raises(ValidationError) as caught:
        _Doc.model_validate("not a mapping")
    assert validation_error_details(caught.value)[0]["loc"] == "<root>"

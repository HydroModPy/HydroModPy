"""Map Pydantic ``ValidationError`` paths back to TOML source lines."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from hydromodpy.core.toml_io.error_locator import (
    format_loc,
    format_validation_error,
    locate_loc,
)


def test_format_loc_renders_dotted_path_with_indices() -> None:
    assert format_loc(("flow", "param_list", 0, "kind")) == "flow.param_list[0].kind"
    assert format_loc(()) == ""
    assert format_loc(("workspace",)) == "workspace"


def test_locate_loc_finds_assignment_under_section() -> None:
    text = textwrap.dedent(
        """\
        [workspace]
        project_root = "/tmp/foo"

        [flow]
        flow_regime = "steady"
        param_list = ["K", "Sy"]
        """
    )
    line = locate_loc(text, ("flow", "param_list"))
    assert line is not None
    assert text.splitlines()[line - 1].startswith("param_list")


def test_locate_loc_falls_back_to_header_for_missing_key() -> None:
    text = textwrap.dedent(
        """\
        [flow]
        flow_regime = "steady"
        """
    )
    assert locate_loc(text, ("flow", "missing_field")) == 1


def test_locate_loc_returns_header_for_root_index() -> None:
    text = textwrap.dedent(
        """\
        [analysis.batch]
        runs = []
        """
    )
    assert locate_loc(text, ("analysis", "batch", "0", "kind")) == 1


def test_format_validation_error_includes_file_and_line(tmp_path: Path) -> None:
    class Inner(BaseModel):
        value: int

    class Outer(BaseModel):
        inner: Inner

    src = tmp_path / "config.toml"
    src.write_text(
        textwrap.dedent(
            """\
            [inner]
            value = "not-an-int"
            """
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError) as excinfo:
        Outer.model_validate({"inner": {"value": "not-an-int"}})

    rendered = format_validation_error(excinfo.value, source_path=src)
    assert str(src) in rendered
    assert "inner.value" in rendered
    assert ":2:" in rendered  # the bad assignment is on line 2

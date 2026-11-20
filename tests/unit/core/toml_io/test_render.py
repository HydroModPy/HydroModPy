"""Python values written as TOML literals, and a free mapping written as nested tables."""

from __future__ import annotations

import tomllib
from datetime import date
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel, Field

from hydromodpy.core.toml_io.render import fmt, render_mapping_value


class Mode(Enum):
    FAST = "fast"


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (None, ""),
        (True, "true"),
        (False, "false"),
        (3, "3"),
        (2.5, "2.5"),
        (Mode.FAST, '"fast"'),
        (Path("a/b"), '"a/b"'),
        (date(2000, 1, 2), '"2000-01-02"'),
        ("plain", '"plain"'),
        (r'C:\data "x"' + "\n", r'"C:\\data \"x\"\n"'),
        ([1, "a", False], '[1, "a", false]'),
        ((1, 2), "[1, 2]"),
        ({"a b": 1, "gone": None, "z": [1]}, '{"a b" = 1, z = [1]}'),
    ],
)
def test_fmt(value: Any, text: str) -> None:
    assert fmt(value) == text


def test_fmt_of_a_quantity() -> None:
    class Units:
        def __format__(self, spec: str) -> str:
            return "m/s" if spec == "~" else "metre/second"

    assert fmt(SimpleNamespace(magnitude=1.5, units=Units())) == '"1.5 m/s"'


def test_a_free_mapping_reloads_as_nested_tables() -> None:
    values = {
        "k": 1.0,
        "none": None,
        "inner": {"a": "x", "deeper": {"b": [1, 2]}},
        "reaches": [{"name": "r1", "opt": None, "sub": {"c": True}}, {"name": "r2"}],
    }

    lines = render_mapping_value("flow.param", values)

    loaded = tomllib.loads("\n".join(lines))["flow"]["param"]
    assert loaded["k"] == 1.0
    assert "none" not in loaded
    assert loaded["inner"] == {"a": "x", "deeper": {"b": [1, 2]}}
    assert [r["name"] for r in loaded["reaches"]] == ["r1", "r2"]
    assert loaded["reaches"][0]["sub"] == {"c": True}


def test_a_model_value_drops_its_none_fields() -> None:
    class Inner(BaseModel):
        a: int = 1
        b: int | None = None

    lines = render_mapping_value("s", {"inner": Inner()})

    assert tomllib.loads("\n".join(lines)) == {"s": {"inner": {"a": 1}}}

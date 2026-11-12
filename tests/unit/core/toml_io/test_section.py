"""A pydantic model written as a commented TOML table, with its descriptions as comments."""

from __future__ import annotations

import tomllib
from datetime import date
from enum import Enum

from pydantic import BaseModel, Field

from hydromodpy.core.toml_io.section import section


class Mode(Enum):
    FAST = "fast"


class Leaf(BaseModel):
    depth_m: float = Field(default=2.0, ge=0.0, description="Depth of the leaf, in metres.")


class Sample(BaseModel):
    name: str = Field(default="nancon", description="Site name.")
    mode: Mode = Mode.FAST
    start: date | None = None
    leaf: Leaf = Field(default_factory=Leaf)
    extra: Leaf | None = None
    leaves: list[Leaf] = Field(default_factory=list)
    table: dict[str, Leaf] = Field(default_factory=dict)


def test_section_text():
    text = "\n".join(section("sample", Sample, 99))

    assert "[sample]" in text
    assert "Site name." in text
    assert "Depth of the leaf, in metres." in text


def test_section_reloads_defaults():
    lines = section("sample", Sample, 99)

    loaded = tomllib.loads("\n".join(lines)).get("sample", {})
    assert Sample.model_validate(loaded) == Sample()

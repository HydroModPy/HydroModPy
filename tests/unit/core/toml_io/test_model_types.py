"""Which Pydantic model a field holds, and which member of a union."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Any, Literal

import pytest
from pydantic import BaseModel, Field

from hydromodpy.core.toml_io.model_types import (
    is_mapping_field,
    resolve_basemodel_type,
    resolve_list_basemodel_type,
    resolve_mapping_basemodel_types,
    restore_variant_tags,
    variant_for_values,
)


class Kind(StrEnum):
    ROCK = "rock"


class Flat(BaseModel):
    kind: Literal["flat"] = "flat"
    elevation: float = 0.0


class Constant(BaseModel):
    kind: Literal["constant"] = "constant"
    thickness: float = 1.0


class Tagged(BaseModel):
    kind: Literal[Kind.ROCK] = Kind.ROCK


class Holder(BaseModel):
    plain: Flat = Field(default_factory=Flat)
    optional: Flat | None = None
    union: Annotated[Flat | Constant, Field(discriminator="kind")] = Field(default_factory=Constant)
    models: list[Flat] = Field(default_factory=list)
    by_union: list[Annotated[Flat | Constant, Field(discriminator="kind")]] = Field(
        default_factory=lambda: [Constant()]
    )
    by_name: dict[str, Flat | Constant] = Field(default_factory=dict)
    free: dict[str, Any] = Field(default_factory=dict)
    abstract: Mapping[str, float] = Field(default_factory=dict)
    number: float = 0.0
    numbers: list[float] = Field(default_factory=list)


def _field(name: str):
    return Holder.model_fields[name]


@pytest.mark.parametrize(
    ("name", "expected"),
    [("by_name", True), ("free", True), ("abstract", True), ("plain", False), ("models", False)],
)
def test_a_mapping_field_is_told_from_a_model_or_a_list(name: str, expected: bool) -> None:
    assert is_mapping_field(_field(name)) is expected


def test_a_default_instance_decides_the_member_of_a_union() -> None:
    class WithDefault(BaseModel):
        either: Flat | Constant = Constant()

    assert resolve_basemodel_type(WithDefault.model_fields["either"]) is Constant


def test_a_default_factory_that_fails_is_ignored() -> None:
    def broken() -> list[Flat]:
        raise RuntimeError("boom")

    class Bare(BaseModel):
        items: list[Flat | Constant] = Field(default_factory=broken)
        either: Flat | Constant = Field(default_factory=broken)

    assert resolve_list_basemodel_type(Bare.model_fields["items"]) is Flat
    assert resolve_basemodel_type(Bare.model_fields["either"]) is Flat


@pytest.mark.parametrize(
    ("name", "expected"),
    [("by_name", [Flat, Constant]), ("free", []), ("plain", []), ("number", [])],
)
def test_the_models_a_mapping_holds(name: str, expected: list[type[BaseModel]]) -> None:
    assert resolve_mapping_basemodel_types(_field(name)) == expected


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ({"kind": "flat"}, Flat),
        ({"kind": "constant"}, Constant),
        ({"kind": "unknown"}, Constant),  # no member claims the tag: the fallback stands
        ({"thickness": 2.0}, Constant),  # no tag
        ("not a table", Constant),
    ],
)
def test_the_member_a_value_pins(values: Any, expected: type[BaseModel]) -> None:
    assert variant_for_values(_field("union"), Constant, values) is expected


def test_an_enum_tag_is_written_as_its_value() -> None:
    values: dict[str, Any] = {}

    restore_variant_tags(Tagged(), values)

    assert values == {"kind": "rock"}


def test_a_tag_already_in_the_dump_and_a_non_table_are_left_alone() -> None:
    values = {"kind": "other"}
    restore_variant_tags(Flat(), values)
    assert values == {"kind": "other"}

    restore_variant_tags(Flat(), "not a table")

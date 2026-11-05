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
    variant_tag_field,
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


def test_an_optional_mapping_is_still_a_mapping() -> None:
    class Optional_(BaseModel):
        table: dict[str, int] | None = None

    assert is_mapping_field(Optional_.model_fields["table"])


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("plain", Flat),
        ("optional", Flat),
        ("union", Constant),  # the default_factory pins the member the field falls back to
        ("models", None),  # a container is not a nested model
        ("by_name", None),
        ("number", None),
    ],
)
def test_the_model_a_field_holds(name: str, expected: type[BaseModel] | None) -> None:
    assert resolve_basemodel_type(_field(name)) is expected


def test_a_union_without_a_default_falls_back_to_its_first_member() -> None:
    class Bare(BaseModel):
        either: Flat | Constant | None = None

    assert resolve_basemodel_type(Bare.model_fields["either"]) is Flat


def test_a_default_instance_decides_the_member_of_a_union() -> None:
    class WithDefault(BaseModel):
        either: Flat | Constant = Constant()

    assert resolve_basemodel_type(WithDefault.model_fields["either"]) is Constant


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("models", Flat),
        ("by_union", Constant),  # the first item of the default_factory wins
        ("numbers", None),
        ("plain", None),
    ],
)
def test_the_model_a_list_holds(name: str, expected: type[BaseModel] | None) -> None:
    assert resolve_list_basemodel_type(_field(name)) is expected


def test_a_list_union_without_a_default_gives_its_first_member() -> None:
    class Bare(BaseModel):
        items: list[Flat | Constant] = Field(default_factory=list)

    assert resolve_list_basemodel_type(Bare.model_fields["items"]) is Flat


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


def test_a_model_pins_itself_with_its_single_value_literal() -> None:
    assert variant_tag_field(Flat) == "kind"
    assert variant_tag_field(Holder) is None


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


def test_without_a_discriminator_the_fallback_stands() -> None:
    assert variant_for_values(_field("optional"), Constant, {"kind": "flat"}) is Constant


def test_the_tags_a_dump_dropped_are_put_back_all_the_way_down() -> None:
    holder = Holder(union=Flat(), by_union=[Flat(), Constant()], plain=Flat())
    dumped = holder.model_dump(exclude_defaults=True)
    assert "kind" not in dumped["union"]

    restore_variant_tags(holder, dumped)

    assert dumped["union"]["kind"] == "flat"
    assert [item["kind"] for item in dumped["by_union"]] == ["flat", "constant"]


def test_an_enum_tag_is_written_as_its_value() -> None:
    values: dict[str, Any] = {}

    restore_variant_tags(Tagged(), values)

    assert values == {"kind": "rock"}


def test_a_tag_already_in_the_dump_and_a_non_table_are_left_alone() -> None:
    values = {"kind": "other"}
    restore_variant_tags(Flat(), values)
    assert values == {"kind": "other"}

    restore_variant_tags(Flat(), "not a table")


def test_the_tags_inside_a_mapping_of_models_are_restored() -> None:
    holder = Holder(by_name={"a": Flat()})
    dumped = {"by_name": {"a": {}, "b": {}}}

    restore_variant_tags(holder, dumped)

    assert dumped["by_name"] == {"a": {"kind": "flat"}, "b": {}}

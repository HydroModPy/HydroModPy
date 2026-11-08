"""The registry lists the sections and scalars of the root configuration model."""

from __future__ import annotations

from typing import Literal

import pytest
from pydantic import Field

from hydromodpy.core.config_kit import registry
from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.root import RootConfig


class _Flow(HydroModelBase):
    k: float = 1.0


class _Mesh(HydroModelBase):
    nx: int = 10


class _Export(HydroModelBase):
    fmt: str = "csv"


class _Station(HydroModelBase):
    code: str = "s"


class _Root(HydroModelBase):
    workflow: Literal["a", "b"] = "a"
    seed: int = Field(default=0, description="Random seed.")
    flow: _Flow = _Flow()
    mesh: _Mesh | None = None
    export: list[_Export] = []
    stations: tuple[_Station, ...] = ()
    tags: list[str] = []


def test_a_section_is_a_field_whose_type_is_a_model_even_when_optional_or_repeated() -> None:
    assert registry.root_sections(_Root) == {
        "flow": _Flow,
        "mesh": _Mesh,
        "export": _Export,
        "stations": _Station,
    }


def test_root_sections_accepts_root_config_wrapper() -> None:
    wrapper = RootConfig(
        model=_Root,
        migrate_layers=lambda layers: [],
        migrate_merged=lambda doc, layers: [],
    )
    assert registry.root_sections(wrapper) == {
        "flow": _Flow,
        "mesh": _Mesh,
        "export": _Export,
        "stations": _Station,
    }


def test_sections_come_in_declaration_order() -> None:
    assert list(registry.root_sections(_Root)) == ["flow", "mesh", "export", "stations"]


def test_an_array_of_tables_is_told_from_a_single_table() -> None:
    assert registry.repeated_root_sections(_Root) == frozenset({"export", "stations"})


def test_scalars_are_the_fields_that_are_not_sections() -> None:
    scalars = registry.root_scalar_fields(_Root)
    assert list(scalars) == ["workflow", "seed", "tags"]
    assert scalars["seed"].description == "Random seed."


def test_the_returned_mapping_can_be_changed_without_touching_the_registry() -> None:
    registry.root_sections(_Root).pop("flow")
    registry.root_scalar_fields(_Root).pop("seed")
    assert "flow" in registry.root_sections(_Root)
    assert "seed" in registry.root_scalar_fields(_Root)


@pytest.mark.parametrize(
    ("annotation", "expected"),
    [
        (_Flow, (_Flow, False)),
        (_Flow | None, (_Flow, False)),
        (list[_Flow], (_Flow, True)),
        (list[_Flow] | None, (_Flow, True)),
        (tuple[_Flow, ...], (_Flow, True)),
        (tuple[_Flow, int], None),
        (tuple[_Flow], None),
        (list[int], None),
        (dict[str, _Flow], None),
        (int, None),
    ],
)
def test_the_shape_of_a_root_field(annotation, expected) -> None:
    assert registry._section_shape(annotation) == expected
    model = registry._resolve_basemodel(annotation)
    assert model is (expected[0] if expected else None)

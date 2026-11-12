"""The registry lists the sections and scalars of the root configuration model."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from hydromodpy.core.config_kit import registry
from hydromodpy.core.config_kit.base import HydroModelBase


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


def test_sections_in_order() -> None:
    assert list(registry.root_sections(_Root)) == ["flow", "mesh", "export", "stations"]


def test_repeated_sections() -> None:
    assert registry.repeated_root_sections(_Root) == frozenset({"export", "stations"})

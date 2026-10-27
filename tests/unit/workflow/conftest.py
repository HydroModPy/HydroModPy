"""Fixtures of the workflow tests: fake mesh engines, and the planner inputs the mesh step reads."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING

import pytest

from hydromodpy.spatial.mesh.model.cell_types import CellType
from tests._helpers.fake_engines import FakeMeshEngine, fake_engine, registered

if TYPE_CHECKING:
    from hydromodpy.spatial.mesh.planning.inputs import PlanningInputs

_CACHED_GRID = {
    "cell_types": (CellType.QUADRILATERAL,),
    "structured": True,
    "graded": False,
    "cell_families": "rasterized",
    "deterministic": False,
    "needs_cache": True,
}
"""A regular grid declared not deterministic, so the mesh step caches what it builds."""


@pytest.fixture
def cached_engine() -> Iterator[type[FakeMeshEngine]]:
    """A registered fake engine the mesh cache protects; ``builds`` counts its builds."""
    with registered(fake_engine("dispatch_probe", **_CACHED_GRID)) as engine:
        yield engine


@pytest.fixture
def graded_engine() -> Iterator[type[FakeMeshEngine]]:
    """The same fake engine declared graded, so the planner smooths the catchment for it."""
    with registered(fake_engine("outline_probe", **{**_CACHED_GRID, "graded": True})) as engine:
        yield engine


@pytest.fixture
def use_planning_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[PlanningInputs], PlanningInputs]:
    """Return a setter: the mesh step then plans from the given inputs, not from the project."""

    def _use(inputs: PlanningInputs) -> PlanningInputs:
        monkeypatch.setattr(
            "hydromodpy.workflow.steps.mesh.planning_inputs", lambda ctx, mesh_cfg: inputs
        )
        return inputs

    return _use

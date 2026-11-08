"""A solver that reads any engine of planar cells does not read a lumped engine.

MODFLOW 6 accepts ``*planar``, and the ``catchment`` engine gives one polygon
cell, so the type of its cells alone would let it through. One cell is no grid for
MODFLOW 6, so the file is refused while it loads, and the message says that the
token leaves lumped engines out. A solver reads a lumped engine only by naming it.
"""

from __future__ import annotations

from typing import Any

import pytest

from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from tests._helpers.fake_engines import fake_engine, registered


def _synthetic(solver: str, engine: str) -> dict[str, Any]:
    """A synthetic run: the river threshold check passes, and the solver check runs last."""
    return {
        "workflow": {"mode": "simulation"},
        "workspace": {"project_root": "."},
        "geographic": {"source_mode": "synthetic"},
        "solver": {"backend": solver},
        "mesh": {"engine": engine},
    }


@pytest.fixture
def lumped_engine():
    """A third-party engine that declares the lumped capability, registered for the test."""
    with registered(fake_engine("fake_lumped", graded=False, lumped=True)) as engine:
        yield engine


@pytest.mark.parametrize(
    ("solver", "named"),
    [
        ("modflow6", "regular, triangle, voronoi"),
        ("modflow_nwt", "regular"),
        ("boussinesq", "triangle"),
    ],
)
def test_no_shipped_solver_reads_the_catchment_engine(solver: str, named: str) -> None:
    with pytest.raises(ValueError) as excinfo:
        HydroModPyConfig.model_validate(_synthetic(solver, "catchment"))
    message = str(excinfo.value)

    assert f"solver {solver!r} reads the meshes of the engines {named}" in message
    assert "mesh.engine is 'catchment'" in message
    assert "run a solver that reads 'catchment'." in message


def test_the_planar_token_says_it_leaves_lumped_engines_out() -> None:
    with pytest.raises(ValueError, match="any engine with planar cells that is not lumped"):
        HydroModPyConfig.model_validate(_synthetic("modflow6", "catchment"))


def test_modflow6_refuses_a_third_party_lumped_engine(lumped_engine: type) -> None:
    with pytest.raises(ValueError, match="mesh.engine is 'fake_lumped'"):
        HydroModPyConfig.model_validate(_synthetic("modflow6", lumped_engine.engine_id))


def test_modflow6_still_reads_a_third_party_engine_of_polygon_cells() -> None:
    with registered(fake_engine("fake_polygon_cells")) as engine:
        cfg = HydroModPyConfig.model_validate(_synthetic("modflow6", engine.engine_id))

    assert cfg.mesh is not None and cfg.mesh.engine == "fake_polygon_cells"

"""The mesh registry: which engines a solver reads.

A reader, a solver that lists the meshes it reads, names engine ids or the token
``*planar``. The token stands for every engine of planar cells that is not
lumped: an engine that meshes the catchment as one cell is read only by a solver
that names it. The engine class is loaded only when its capabilities decide.
The config refuses a pair of solver and engine that the rule leaves out.
"""

from __future__ import annotations

from typing import Any

import pytest

from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.mesh.port import ANY_PLANAR_ENGINE
from hydromodpy.mesh.registry import engine_accepted
from tests._helpers.fake_engines import fake_engine, registered

pytestmark = pytest.mark.fast


def synthetic_run(solver: str, engine: str) -> dict[str, Any]:
    # The river threshold check passes, so the solver check runs last.
    return {
        "workflow": {"mode": "simulation"},
        "workspace": {"project_root": "."},
        "geographic": {"source_mode": "synthetic"},
        "solver": {"backend": solver},
        "mesh": {"engine": engine},
    }


def test_unknown_engine():
    with pytest.raises(MeshRequestError, match="quadtree"):
        engine_accepted({ANY_PLANAR_ENGINE}, "quadtree")
    assert not engine_accepted({"regular"}, "quadtree")


def test_planar_token_leaves_lumped_out():
    with pytest.raises(ValueError, match="any engine with planar cells that is not lumped"):
        HydroModPyConfig.model_validate(synthetic_run("modflow6", "catchment"))


def test_modflow6_refuses_a_third_party_lumped_engine():
    with registered(fake_engine("fake_lumped", graded=False, lumped=True)) as engine:
        with pytest.raises(ValueError, match="mesh.engine is 'fake_lumped'"):
            HydroModPyConfig.model_validate(synthetic_run("modflow6", engine.engine_id))

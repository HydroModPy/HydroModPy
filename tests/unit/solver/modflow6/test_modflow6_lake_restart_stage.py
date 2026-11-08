"""Lake-stage hotstart: extractor helper, writer contract, and the LAK builder.

Covers the ``[flow] restart_from`` lake companion of the heads restart:
``final_lake_stages`` (last-step stage per lake), the round-trip proving
``SimulationZarr.write_lake_restart_state`` writes the exact group
``read_restart_lake_stages`` expects, and the LAK builder that seeds each lake
from the ``PriorState`` the ``prepare_solver`` step read.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.model.boundaries.boundary_condition_registry import BoundaryConditionBundle
from hydromodpy.results.storage.prior_state import read_restart_lake_stages
from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr
from hydromodpy.solver.modflow6.extractors.lake import final_lake_stages
from tests._helpers.model_factory import make_model
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays


def test_final_lake_stages_keeps_last_step_per_lake() -> None:
    """The helper takes the largest-timestep stage per lake, ignoring non-stage."""
    timeseries = [
        {"station_id": "lake:forebay", "variable": "stage", "timestep": 0, "value": 80.0},
        {"station_id": "lake:forebay", "variable": "stage", "timestep": 1, "value": 86.9},
        {"station_id": "lake:forebay", "variable": "volume", "timestep": 1, "value": 999.0},
        {"station_id": "lake:sill", "variable": "stage", "timestep": 0, "value": 74.0},
        # A non-lake station (e.g. a gauge) must never leak into the lake map.
        {"station_id": "gauge:x", "variable": "stage", "timestep": 5, "value": 1.0},
    ]
    assert final_lake_stages(timeseries) == {"forebay": 86.9, "sill": 74.0}


def test_final_lake_stages_empty() -> None:
    assert final_lake_stages([]) == {}


def test_write_then_read_restart_state_contract(tmp_path: Path) -> None:
    """SimulationZarr writes the exact group the solver reader consumes."""
    sz = SimulationZarr.create(tmp_path / "sim.zarr", n_cells=4, n_layers=1)
    sz.write_lake_restart_state({"forebay": 86.93, "sill": 74.15})
    sz.close()

    stages = read_restart_lake_stages(str(tmp_path / "sim.zarr"))
    assert stages == {"forebay": pytest.approx(86.93), "sill": pytest.approx(74.15)}


def test_write_restart_state_empty_is_noop(tmp_path: Path) -> None:
    sz = SimulationZarr.create(tmp_path / "sim.zarr", n_cells=4, n_layers=1)
    sz.write_lake_restart_state({})
    sz.close()
    assert read_restart_lake_stages(str(tmp_path / "sim.zarr")) == {}


def test_build_lak_uses_restart_stage_over_stageinit(tmp_path: Path) -> None:
    """build_lak_package_args seeds strt from the prior state, overriding initial_stage.

    A lake present in the prior run's lake stages takes its last stage; a lake absent
    from them (partial restart, added lake) keeps its ``initial_stage``.
    """
    from types import SimpleNamespace

    from shapely.geometry import Polygon

    from hydromodpy.model.initial.state import PriorState
    from hydromodpy.solver.modflow6.builders.lake import build_lak_package_args
    from hydromodpy.solver.modflow6.builders.lake_cells import apply_lake_idomain_mask
    from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh

    # lac1 is absent on purpose.
    prior = PriorState(head=np.zeros((2, 16)), lake_stages={"lac0": 88.5}, path="prior.zarr")

    top = np.full((4, 4), 100.0)
    botm = np.stack([np.full((4, 4), 100.0 - (lay + 1) * 50.0) for lay in range(2)])
    mesh = solver_mesh_from_structured_arrays(nrow=4, ncol=4, top=top, botm=botm, dx=1.0, dy=1.0)
    model = SimpleNamespace(
        model_output_name="restart_test",
        time_units="seconds",
        inputs=make_model(
            boundaries=BoundaryConditionBundle(conditions={}, active_ids=("lake",)),
            initial=prior,
            lakes={
                "lac0": {
                    "polygon": Polygon([(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]),
                    "bedleak": 0.2,
                    "abacus": [(50.0, 0.0, 4.0), (90.0, 160.0, 4.0)],
                    "initial_stage": 60.0,
                    "outlets": [],
                },
                "lac1": {
                    "polygon": Polygon([(2.0, 2.0), (4.0, 2.0), (4.0, 4.0), (2.0, 4.0)]),
                    "bedleak": 0.2,
                    "abacus": [(50.0, 0.0, 9.0), (90.0, 360.0, 9.0)],
                    "initial_stage": 70.0,
                    "outlets": [],
                },
            },
        ),
    )
    cells = {"lac0": [0, 1], "lac1": [10, 11]}
    masked = apply_lake_idomain_mask(mesh, lake_cell_ids_by_lake=cells)
    args = build_lak_package_args(model, solver_mesh=masked, lake_cell_ids_by_lake=cells)

    assert args is not None
    strt_by_name = {row[3]: row[1] for row in args["packagedata"]}
    assert strt_by_name["lac0"] == pytest.approx(88.5)  # restart wins over initial_stage 60
    assert strt_by_name["lac1"] == pytest.approx(70.0)  # absent from restart -> initial_stage kept

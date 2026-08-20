"""Lake-stage hotstart: extractor helper, solver reader, and writer contract.

Covers the ``[flow] restart_from`` lake companion of the heads restart:
``final_lake_stages`` (last-step stage per lake), ``read_restart_lake_stages``
(raw-Zarr reader used by the LAK builder), and the round-trip proving
``SimulationZarr.write_lake_restart_state`` writes the exact group the reader
expects.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr
from hydromodpy.solver.modflow6.builders.initial_conditions import read_restart_lake_stages
from hydromodpy.solver.modflow6.extractors.lake import final_lake_stages


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


def test_read_restart_lake_stages_roundtrip_raw_zarr(tmp_path: Path) -> None:
    """The reader parses the ``lake_state_final`` group written by the store."""
    import zarr

    path = tmp_path / "prior.zarr"
    root = zarr.open(str(path), mode="w")
    grp = root.require_group("lake_state_final")
    grp["stage"] = np.array([86.9, 74.2])
    grp.attrs["lake_ids"] = ["forebay", "sill"]

    stages = read_restart_lake_stages(str(path))
    assert stages == {"forebay": pytest.approx(86.9), "sill": pytest.approx(74.2)}


def test_read_restart_lake_stages_absent_group_returns_empty(tmp_path: Path) -> None:
    """A prior run with no lake (no group) yields {} so stageinit is kept."""
    import zarr

    path = tmp_path / "prior.zarr"
    zarr.open(str(path), mode="w")["head"] = np.zeros((1, 1, 3))
    assert read_restart_lake_stages(str(path)) == {}


def test_read_restart_lake_stages_length_mismatch_returns_empty(tmp_path: Path) -> None:
    """A corrupt group (ids vs stages length mismatch) is refused, not guessed."""
    import zarr

    path = tmp_path / "prior.zarr"
    root = zarr.open(str(path), mode="w")
    grp = root.require_group("lake_state_final")
    grp["stage"] = np.array([1.0, 2.0, 3.0])
    grp.attrs["lake_ids"] = ["a", "b"]
    assert read_restart_lake_stages(str(path)) == {}


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


def _write_prior_lake_stage(path: Path, stages: dict[str, float]) -> None:
    import zarr

    grp = zarr.open(str(path), mode="w").require_group("lake_state_final")
    lake_ids = list(stages)
    grp["stage"] = np.array([stages[k] for k in lake_ids], dtype="float64")
    grp.attrs["lake_ids"] = lake_ids


def test_build_lak_uses_restart_stage_over_stageinit(tmp_path: Path) -> None:
    """build_lak_package_args seeds strt from restart_from, overriding stageinit.

    A lake present in the prior run's ``lake_state_final`` takes its last stage; a
    lake absent from it (partial restart, added lake) keeps its ``stageinit``.
    """
    from types import SimpleNamespace

    from shapely.geometry import Polygon

    from hydromodpy.solver.modflow6.builders import (
        apply_lake_idomain_mask,
        build_lak_package_args,
    )
    from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh

    prior = tmp_path / "prior.zarr"
    _write_prior_lake_stage(prior, {"lac0": 88.5})  # lac1 absent on purpose

    top = np.full((4, 4), 100.0)
    botm = np.stack([np.full((4, 4), 100.0 - (lay + 1) * 50.0) for lay in range(2)])
    mesh = SolverMesh.from_structured_arrays(nrow=4, ncol=4, top=top, botm=botm, dx=1.0, dy=1.0)
    model = SimpleNamespace(
        model_output_name="restart_test",
        time_units="seconds",
        flow=SimpleNamespace(
            active_bc=["reservoir"],
            restart_from=str(prior),
            sinks_sources={
                "lakes": {
                    "lac0": {
                        "polygon": Polygon([(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]),
                        "bedleak": 0.2,
                        "abacus": [(50.0, 0.0, 4.0), (90.0, 160.0, 4.0)],
                        "stageinit": 60.0,
                        "outlets": [],
                    },
                    "lac1": {
                        "polygon": Polygon([(2.0, 2.0), (4.0, 2.0), (4.0, 4.0), (2.0, 4.0)]),
                        "bedleak": 0.2,
                        "abacus": [(50.0, 0.0, 9.0), (90.0, 360.0, 9.0)],
                        "stageinit": 70.0,
                        "outlets": [],
                    },
                }
            },
        ),
    )
    cells = {"lac0": [0, 1], "lac1": [10, 11]}
    masked = apply_lake_idomain_mask(mesh, lake_cell_ids_by_lake=cells)
    args = build_lak_package_args(model, solver_mesh=masked, lake_cell_ids_by_lake=cells)

    assert args is not None
    strt_by_name = {row[3]: row[1] for row in args["packagedata"]}
    assert strt_by_name["lac0"] == pytest.approx(88.5)  # restart wins over stageinit 60
    assert strt_by_name["lac1"] == pytest.approx(70.0)  # absent from restart -> stageinit kept

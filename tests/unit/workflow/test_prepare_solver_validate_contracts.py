from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import hydromodpy.workflow.steps.prepare_solver.validate as validate_module
from hydromodpy.core.exceptions import PipelineError


class _DumpableConfig:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload
        self.flow = SimpleNamespace(flow_regime="transient")
        self.simulation = SimpleNamespace(
            description="Demo run",
            scientific_objective="Water budget",
            contact_email="",
            doi=None,
            study_area_name="Demo basin",
            outlet_x=1.25,
            outlet_y=None,
            time=SimpleNamespace(step_unit="days"),
        )
        self.geographic = SimpleNamespace(crs_project="EPSG:2154")

    def model_dump(self, **_kwargs) -> dict[str, object]:
        return dict(self._payload)


def test_primary_solver_skips_mesh_runs_and_uses_first_solver_backed_run() -> None:
    plan = SimpleNamespace(
        runs=(
            SimpleNamespace(process_type="mesh", solver="catchment"),
            SimpleNamespace(process_type="flow", solver="modflow6"),
            SimpleNamespace(process_type="transport", solver="mt3dms"),
        )
    )

    assert validate_module._primary_solver_for_simulation(plan) == "modflow6"


def test_primary_solver_uses_mesh_solver_for_mesh_only_plan() -> None:
    plan = SimpleNamespace(runs=(SimpleNamespace(process_type="mesh", solver="catchment"),))

    assert validate_module._primary_solver_for_simulation(plan) == "catchment"


def test_primary_solver_rejects_empty_plan() -> None:
    with pytest.raises(PipelineError, match="SimulationPlan has no runs"):
        validate_module._primary_solver_for_simulation(SimpleNamespace(runs=()))


def test_collect_registration_kwargs_collects_mesh_time_and_simulation_metadata(
    tmp_path: Path,
) -> None:
    points = np.array([[0.0, 0.0], [1.0, 0.0]], dtype=np.float64)
    connectivity = np.array([[0, 1]], dtype=np.int32)
    mesh = SimpleNamespace(
        n_cells=2,
        cell_type="triangle",
        bounds=(0.0, 1.0, 2.0, 3.0),
        points_xy=points,
        connectivity=connectivity,
    )
    cfg_payload = {
        "flow": {"flow_regime": "transient"},
        "simulation": {"results": {"keep_solver_files": False}},
    }
    ctx = SimpleNamespace(
        config_path=tmp_path / "config.toml",
        cfg=_DumpableConfig(cfg_payload),
        setup=SimpleNamespace(
            mesh_planar=mesh,
            time_grid=SimpleNamespace(boundaries=("2020-01-01", "2020-01-02", "2020-01-03")),
            domain=None,
        ),
        effective_results_config=None,
    )

    kwargs = validate_module.collect_registration_kwargs(ctx)

    expected_mesh_hash = hashlib.sha256(points.tobytes() + connectivity.tobytes()).hexdigest()
    assert kwargs["flow_regime"] == "transient"
    assert kwargs["config_source"] == str(tmp_path / "config.toml")
    assert kwargs["config"] == cfg_payload
    assert kwargs["config_snapshot"] == cfg_payload
    assert kwargs["description"] == "Demo run"
    assert kwargs["scientific_objective"] == "Water budget"
    assert kwargs["study_area_name"] == "Demo basin"
    assert kwargs["outlet_x"] == 1.25
    assert "contact_email" not in kwargs
    assert "doi" not in kwargs
    assert "outlet_y" not in kwargs
    assert kwargs["n_cells"] == 2
    assert kwargs["mesh_type"] == "triangle"
    assert kwargs["cell_types"] == ["triangle"]
    assert kwargs["bbox"] == [0.0, 1.0, 2.0, 3.0]
    assert kwargs["mesh_hash"] == expected_mesh_hash
    assert kwargs["crs"] == "EPSG:2154"
    assert kwargs["period_start"] == "2020-01-01"
    assert kwargs["period_end"] == "2020-01-03"
    assert kwargs["n_timesteps"] == 2
    assert kwargs["time_unit"] == "days"


def test_store_sim_artifacts_returns_existing_workspace_relative_store_paths(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    zarr_path = project_root / "simulations" / "sim-123.zarr"
    parquet_dir = project_root / "exports" / "sim-123"
    zarr_path.mkdir(parents=True)
    parquet_dir.mkdir(parents=True)

    store = SimpleNamespace(
        zarr_path_for=lambda sim_id: zarr_path,
        parquet_dir_for=lambda sim_id: parquet_dir,
    )
    ctx = SimpleNamespace(
        store=store,
        setup=SimpleNamespace(workspace=SimpleNamespace(project_root=project_root)),
    )

    assert validate_module._store_sim_artifacts(ctx, "sim-123") == (
        "simulations/sim-123.zarr",
        "exports/sim-123",
    )


def test_store_sim_artifacts_ignores_missing_and_external_paths(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    external = tmp_path / "external.zarr"
    external.mkdir()
    missing = project_root / "exports" / "missing"
    store = SimpleNamespace(
        zarr_path_for=lambda sim_id: external,
        parquet_dir_for=lambda sim_id: missing,
    )
    ctx = SimpleNamespace(
        store=store,
        setup=SimpleNamespace(workspace=SimpleNamespace(project_root=project_root)),
    )

    assert validate_module._store_sim_artifacts(ctx, "sim-123") == ()

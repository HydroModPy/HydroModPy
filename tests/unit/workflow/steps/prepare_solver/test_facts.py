"""Facts of a run: its primary solver, its mesh (hash, bbox, cells), its period and its artifact paths."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import hydromodpy.workflow.steps.prepare_solver.facts as facts_module
from hydromodpy.core.exceptions import PipelineError
from hydromodpy.core.state.layout import RUNS_DIRNAME
from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.results.storage.contract import FIELDS_STORE_NAME, TABLES_DIRNAME
from tests._helpers.cell_meshes import cell_mesh_of
from tests.unit.workflow.steps.prepare_solver._helpers import square_and_pentagon


class DumpableConfig:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload
        self.flow = SimpleNamespace(flow_regime="transient")
        self.simulation = SimpleNamespace(
            description="Demo run",
            scientific_objective="Water budget",
            contact_email="",
            doi=None,
            time=SimpleNamespace(step_unit="days"),
        )
        self.geographic = SimpleNamespace(crs_project="EPSG:2154")
        self.site = None

    def model_dump(self, **_kwargs) -> dict[str, object]:
        return dict(self._payload)


PRIMARY_RUNS = [
    pytest.param(
        [("mesh", "catchment"), ("flow", "modflow6"), ("transport", "mt3dms")],
        ("flow", "modflow6"),
        id="first solver run",
    ),
    pytest.param([("mesh", "catchment")], ("mesh", "catchment"), id="mesh only"),
]


@pytest.mark.parametrize(("runs", "primary"), PRIMARY_RUNS)
def test_primary_run(runs, primary) -> None:
    plan = SimpleNamespace(
        runs=tuple(SimpleNamespace(process_type=kind, solver=solver) for kind, solver in runs)
    )

    assert facts_module.primary_run_for_simulation(plan) == primary


def test_primary_run_of_an_empty_plan_is_refused() -> None:
    with pytest.raises(PipelineError, match="SimulationPlan has no runs"):
        facts_module.primary_run_for_simulation(SimpleNamespace(runs=()))


def test_run_facts_of_a_triangle_mesh(tmp_path: Path) -> None:
    points = np.array([[0.0, 0.0], [2.0, 0.0], [2.0, 3.0], [0.0, 3.0]], dtype=np.float64)
    connectivity = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64)
    cell_mesh = cell_mesh_of(
        HydroMesh(
            vertices=points,
            cell_blocks=(CellBlock(CellType.TRIANGLE, connectivity),),
        )
    )
    cfg_payload = {
        "flow": {"flow_regime": "transient"},
        "simulation": {"results": {"keep_solver_files": False}},
    }
    ctx = SimpleNamespace(
        config_path=tmp_path / "config.toml",
        cfg=DumpableConfig(cfg_payload),
        setup=SimpleNamespace(
            cell_mesh=cell_mesh,
            time_grid=SimpleNamespace(boundaries=("2020-01-01", "2020-01-02", "2020-01-03")),
            domain=None,
        ),
    )

    facts = facts_module.collect_run_facts(ctx)

    expected_mesh_hash = hashlib.sha256(points.tobytes() + connectivity.tobytes()).hexdigest()
    assert facts["flow_regime"] == "transient"
    assert facts["config_source"] == str(tmp_path / "config.toml")
    assert facts["description"] == "Demo run"
    assert facts["scientific_objective"] == "Water budget"
    assert "contact_email" not in facts
    assert "doi" not in facts
    assert "study_area_name" not in facts
    assert facts["n_cells"] == 2
    assert facts["mesh_topology"] == "triangle"
    assert facts["bbox"] == (0.0, 0.0, 2.0, 3.0)
    assert facts["mesh_hash"] == expected_mesh_hash
    assert facts["crs_wkt"] == "EPSG:2154"
    assert facts["crs_epsg"] == 2154
    assert facts["period_start"].isoformat() == "2020-01-01T00:00:00+00:00"
    assert facts["period_end"].isoformat() == "2020-01-03T00:00:00+00:00"
    assert facts["n_timesteps"] == 2
    assert facts["time_unit"] == "days"
    assert "site" not in facts


def test_artifacts_are_project_relative_paths(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    run_dir = project_root / RUNS_DIRNAME / "demo_run"
    fields_path = run_dir / FIELDS_STORE_NAME
    tables_dir = run_dir / TABLES_DIRNAME
    fields_path.mkdir(parents=True)
    tables_dir.mkdir(parents=True)

    store = SimpleNamespace(
        fields_path_for=lambda sim_id: fields_path,
        tables_dir_for=lambda sim_id: tables_dir,
    )
    ctx = SimpleNamespace(
        setup=SimpleNamespace(workspace=SimpleNamespace(project_root=project_root)),
    )

    assert facts_module.store_sim_artifacts(ctx, "sim-123", store=store) == (
        f"{RUNS_DIRNAME}/demo_run/{FIELDS_STORE_NAME}",
        f"{RUNS_DIRNAME}/demo_run/{TABLES_DIRNAME}",
    )


def test_artifacts_skip_missing_and_external_paths(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    external = tmp_path / "external" / FIELDS_STORE_NAME
    external.mkdir(parents=True)
    missing = project_root / RUNS_DIRNAME / "gone" / TABLES_DIRNAME
    store = SimpleNamespace(
        fields_path_for=lambda sim_id: external,
        tables_dir_for=lambda sim_id: missing,
    )
    ctx = SimpleNamespace(
        setup=SimpleNamespace(workspace=SimpleNamespace(project_root=project_root)),
    )

    assert facts_module.store_sim_artifacts(ctx, "sim-123", store=store) == ()


# A polygon mesh (a Voronoi dual) has rows of different lengths. The registration hash needs
# the rectangular rows padded with -1.
PADDED = np.array([[0, 1, 2, 3, -1], [1, 4, 5, 6, 2]])


def polygon_ctx(
    cell_mesh: object, z_interfaces: tuple[float, ...] = (0.0, -10.0)
) -> SimpleNamespace:
    return SimpleNamespace(
        config_path=None,
        cfg=SimpleNamespace(
            flow=SimpleNamespace(flow_regime="steady"),
            simulation=None,
            geographic=SimpleNamespace(crs_project="EPSG:2154"),
            site=None,
            model_dump=lambda mode="json": {},
        ),
        setup=SimpleNamespace(
            cell_mesh=cell_mesh,
            mesh_summary=None,
            time_grid=None,
            domain=SimpleNamespace(z_interfaces=np.array(z_interfaces)),
        ),
    )


def test_run_facts_of_a_polygon_mesh() -> None:
    cell_mesh = cell_mesh_of(square_and_pentagon())

    facts = facts_module.collect_run_facts(polygon_ctx(cell_mesh))

    expected = hashlib.sha256(
        cell_mesh.mesh.vertices.tobytes() + PADDED.astype(np.int32).tobytes()
    ).hexdigest()
    assert facts["mesh_hash"] == expected
    assert facts["n_cells"] == 2
    assert facts["mesh_topology"] == "polygon"

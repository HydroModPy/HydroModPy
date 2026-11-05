"""The facts of the run."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import BaseModel, ConfigDict

import hydromodpy.workflow.steps.prepare_solver.facts as facts_module
from hydromodpy.core.exceptions import PipelineError
from hydromodpy.core.site import SiteConfig
from hydromodpy.core.state.paths import PROJECT_MARKER_FILENAME, RUNS_DIRNAME
from hydromodpy.results.catalog.registration import reserve_version_dirname
from hydromodpy.results.lineage import Lineage
from hydromodpy.results.outcome import read_outcome
from hydromodpy.results.storage.attempt import claim_run_directory
from hydromodpy.results.storage.contract import FIELDS_STORE_NAME, TABLES_DIRNAME
from hydromodpy.results.zarr_store import SimulationZarr
from hydromodpy.spatial.domain.domain_config import DomainConfig
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.workflow.steps.prepare_solver import prepare as prepare_module
from hydromodpy.workflow.steps.prepare_solver.dispatch import bind_run_directory, initial_facts
from hydromodpy.workflow.steps.prepare_solver.facts import (
    collect_effective_config_snapshot,
    site_block,
)
from tests._helpers.cell_meshes import cell_mesh_of
from tests.unit.workflow.steps.prepare_solver._helpers import square_and_pentagon


class _DumpableConfig:
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


def test_primary_solver_skips_mesh_runs_and_uses_first_solver_backed_run() -> None:
    plan = SimpleNamespace(
        runs=(
            SimpleNamespace(process_type="mesh", solver="catchment"),
            SimpleNamespace(process_type="flow", solver="modflow6"),
            SimpleNamespace(process_type="transport", solver="mt3dms"),
        )
    )

    assert facts_module.primary_solver_for_simulation(plan) == "modflow6"


def test_primary_solver_uses_mesh_solver_for_mesh_only_plan() -> None:
    plan = SimpleNamespace(runs=(SimpleNamespace(process_type="mesh", solver="catchment"),))

    assert facts_module.primary_solver_for_simulation(plan) == "catchment"


def test_primary_solver_rejects_empty_plan() -> None:
    with pytest.raises(PipelineError, match="SimulationPlan has no runs"):
        facts_module.primary_solver_for_simulation(SimpleNamespace(runs=()))


def test_collect_run_facts_collects_mesh_time_and_simulation_metadata(
    tmp_path: Path,
) -> None:
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
        cfg=_DumpableConfig(cfg_payload),
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


def test_store_sim_artifacts_returns_existing_project_relative_run_paths(
    tmp_path: Path,
) -> None:
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


def test_store_sim_artifacts_ignores_missing_and_external_paths(tmp_path: Path) -> None:
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


# --- test_the_seal_names_the_gauge_the_run_used ---
# The ``site`` block of the seal names the gauge the run was compared to.
#
# ``[site] gauge`` when it is declared; else the single hydrometric station the
# run loaded; with none or several, no gauge.


def _ctx(site: SiteConfig, stations: tuple[str, ...]) -> SimpleNamespace:
    catchment = SimpleNamespace(kind="from_outlet_coord", x_outlet=1.0, y_outlet=2.0)
    hydrometry = SimpleNamespace(points=[SimpleNamespace(station_id=s) for s in stations])
    return SimpleNamespace(
        cfg=SimpleNamespace(
            site=site,
            geographic=SimpleNamespace(catchment=catchment, crs_project="EPSG:2154"),
        ),
        loaded_data=SimpleNamespace(hydrometry=hydrometry),
    )


@pytest.mark.parametrize(
    ("declared", "stations", "gauge"),
    [
        ("J0014010", ("J0014010", "J0000001"), "J0014010"),
        (None, ("J0014010",), "J0014010"),
        (None, ("J0014010", "J0000001"), None),
        (None, (), None),
    ],
)
def test_the_gauge_is_declared_or_the_single_station_loaded(
    declared: str | None, stations: tuple[str, ...], gauge: str | None
) -> None:
    block = site_block(_ctx(SiteConfig(name="nancon", gauge=declared), stations))

    assert block is not None
    assert block.gauge == gauge


# --- test_store_handle_lifecycle ---
# The run directory is bound once, by the step that opens the run.
#
# ``bind_run_directory`` reads the identity of the attempt off the outcome of
# the directory it is handed, or claims the directory of the case when it is
# handed none; the facts of the attempt are built from the context, written by
# the store that opens on them, and no handle survives the step.


class _Results(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keep_solver_files: bool = True
    budget_keep: str = "all"


class _Simulation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    results: _Results = _Results()


class _Workflow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str = "auto"


class _RunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow: _Workflow = _Workflow()
    domain: DomainConfig = DomainConfig()
    simulation: _Simulation = _Simulation()


def test_effective_config_snapshot_is_the_run_config_with_the_runtime_domain() -> None:
    """Nothing is forced at planning: the results section is the one written."""
    declared = {
        "workflow": {"mode": "simulation"},
        "domain": {"depth_model": {"kind": "constant_thickness", "thickness": 10.0}},
        "simulation": {"results": {"keep_solver_files": False}},
    }
    effective_domain = {
        "depth_model": {"kind": "constant_thickness", "thickness": 25.0},
    }
    ctx = SimpleNamespace(
        cfg=_RunConfig.model_validate(declared),
        setup=SimpleNamespace(
            domain=SimpleNamespace(config=DomainConfig.model_validate(effective_domain))
        ),
    )

    snapshot = collect_effective_config_snapshot(ctx)

    assert snapshot["domain"] == effective_domain
    assert snapshot["simulation"] == declared["simulation"]
    assert snapshot["workflow"] == declared["workflow"]


# --- test_a_ragged_mesh_registers_and_persists ---
# A polygon mesh (a Voronoi dual) registers and persists like a triangle mesh.
#
# Its connectivity is a tuple of rows of different lengths: the registration hash
# and the Zarr writer both need the ``-1`` padded rectangular rows instead.

PADDED = np.array([[0, 1, 2, 3, -1], [1, 4, 5, 6, 2]])


def _ragged_ctx(
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


def test_the_registration_hashes_the_padded_rows_of_a_polygon_mesh() -> None:
    cell_mesh = cell_mesh_of(square_and_pentagon())

    facts = facts_module.collect_run_facts(_ragged_ctx(cell_mesh))

    expected = hashlib.sha256(
        cell_mesh.mesh.vertices.tobytes() + PADDED.astype(np.int32).tobytes()
    ).hexdigest()
    assert facts["mesh_hash"] == expected
    assert facts["n_cells"] == 2
    assert facts["mesh_topology"] == "polygon"

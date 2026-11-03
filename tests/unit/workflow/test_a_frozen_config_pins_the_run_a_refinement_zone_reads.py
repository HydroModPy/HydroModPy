"""The frozen config names the run a refinement zone read by its sim_id, not by its name.

A zone that reads an earlier run writes ``run = "<name>"``, and a bare name is
the latest version of that run. After a ``.v2`` of the first run, a replay
(``hmp catalog rerun`` reads the frozen snapshot, ``hmp run --resume`` the
frozen file) would read the ``.v2`` and draw another mesh. The mesh step keeps
the sim_id each zone read, and the freeze writes it in place of the name.
"""

from __future__ import annotations

import shutil
import tomllib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from shapely.geometry import box

from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.results.catalog.registration import config_identity_hash
from hydromodpy.results.storage.attempt import _config_changed
from hydromodpy.results.storage.contract import RUN_CONFIG_FILENAME
from hydromodpy.results.storage.sealing import seal_completed
from hydromodpy.spatial.mesh.mesh_config import MeshConfig
from hydromodpy.spatial.mesh.planning.refinement_zones import (
    CriterionInputs,
    RefinementZone,
    load_refinement_zones,
)
from hydromodpy.spatial.mesh.refinement_config import RefinementZoneConfig
from hydromodpy.workflow.steps import mesh as mesh_module
from hydromodpy.workflow.steps.mesh import _zone_runs, step_mesh
from hydromodpy.workflow.steps.mesh_run_fields import read_run_fields
from hydromodpy.workflow.steps.prepare_solver.dispatch import (
    _freeze_run_config,
    frozen_config_document,
)
from tests._helpers.mesh_cases import grid_spec, planning_inputs
from tests._helpers.run_stores import open_run_store

CELL = 100.0
GRID = grid_spec(8, 8, 25.0)
ZONE = {"where": "watertable_depth", "below": 0.5, "run": "coarse", "cell_size": 25.0}


def _source_run(project: Path, name: str) -> str:
    """Seal a run of four cells whose water table is 0.25 m deep in the first one."""
    store = open_run_store(project, name, n_cells=4, n_layers=1, n_timesteps=1)
    sim_id = store.sim_id
    xs = np.array([0.0, CELL, 2 * CELL])
    vertices = np.array([[x, y, 0.0] for y in xs for x in xs])
    connectivity = np.array([[0, 1, 4, 3], [1, 2, 5, 4], [3, 4, 7, 6], [4, 5, 8, 7]])
    handle = store.open_zarr(sim_id)
    try:
        handle.write_mesh(
            vertices,
            connectivity.astype("int32"),
            np.array([100.0, 50.0]),
            topography=np.full(4, 100.0),
        )
        handle.write_field_stack("head", np.array([[[99.75, 95.0, 95.0, 95.0]]]).transpose(0, 2, 1))
    finally:
        handle.close()
    seal_completed(store)
    return sim_id


def _config(project: Path, *zones: dict) -> HydroModPyConfig:
    return HydroModPyConfig.model_validate(
        {
            "workflow": {"mode": "simulation"},
            "workspace": {"project_root": str(project)},
            "site": {"name": "site_a"},
            "geographic": {
                "catchment": {"catch_def": "dem", "dem_init_path": "dem.tif"},
                "river_network": {"threshold_area_km2": 0.5},
            },
            "mesh": {
                "engine": "voronoi",
                "families": {"rivers": "none"},
                "refinement_zone": list(zones),
            },
        }
    )


def _read_by_the_mesh_step(project: Path, cfg: HydroModPyConfig) -> dict[str, str]:
    """What the mesh step keeps of the zones: the sim_id each ``run`` reference resolved to."""
    zones = cfg.mesh.refinement_zone
    planned = load_refinement_zones(
        zones,
        config_dir=None,
        data_dir=None,
        crs_wkt=GRID.crs_wkt,
        criteria=CriterionInputs(
            grid=GRID,
            elevation=np.zeros((8, 8)),
            stream_lines=None,
            run_fields=read_run_fields(project, zones),
        ),
    )
    return _zone_runs(zones, planned)


def _freeze(project: Path, cfg: HydroModPyConfig, zone_runs: dict[str, str], name: str) -> Path:
    """Freeze *cfg* into ``runs/<name>`` through the step that opens a run."""
    store = open_run_store(project, name, n_cells=4)
    summary = {"zone_runs": zone_runs}
    ctx = SimpleNamespace(
        cfg=cfg,
        run_dir=store.run_dir,
        loaded_data=None,
        setup=SimpleNamespace(domain=None, flow=None, mesh_summary=summary),
    )
    _freeze_run_config(ctx, store=store)
    store.close()
    return store.run_dir / RUN_CONFIG_FILENAME


def _replayed(project: Path, frozen: Path) -> HydroModPyConfig:
    """The configuration ``hmp catalog rerun`` rebuilds from a frozen file."""
    snapshot = tomllib.loads(frozen.read_text(encoding="utf-8"))
    snapshot.setdefault("workspace", {})["project_root"] = str(project)
    return HydroModPyConfig.from_snapshot(snapshot)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return tmp_path / "workspace"


def test_the_frozen_zone_names_the_run_by_sim_id(project: Path) -> None:
    sim_id = _source_run(project, "coarse")
    cfg = _config(project, ZONE)

    frozen = _freeze(project, cfg, _read_by_the_mesh_step(project, cfg), "production")

    written = tomllib.loads(frozen.read_text(encoding="utf-8"))["mesh"]["refinement_zone"]
    assert written == [{**ZONE, "run": sim_id}]
    assert cfg.mesh.refinement_zone[0].run == "coarse", "the live configuration keeps the name"


def test_a_replay_reads_the_run_the_mesh_came_from_after_a_later_version(project: Path) -> None:
    first = _source_run(project, "coarse")
    cfg = _config(project, ZONE)
    frozen = _freeze(project, cfg, _read_by_the_mesh_step(project, cfg), "production")

    second = _source_run(project, "coarse")
    assert second != first
    assert (
        read_run_fields(project, cfg.mesh.refinement_zone)[("coarse", "watertable_depth")].sim_id
        == second
    ), "the bare name now reads the .v2"
    replayed = _replayed(project, frozen)

    envelope = read_run_fields(project, replayed.mesh.refinement_zone)
    (read,) = envelope.values()
    assert read.sim_id == first and read.run == "coarse"
    assert _read_by_the_mesh_step(project, replayed) == {first: first}


def test_a_second_freeze_of_a_replay_writes_the_same_sim_id(project: Path) -> None:
    first = _source_run(project, "coarse")
    cfg = _config(project, ZONE)
    frozen = _freeze(project, cfg, _read_by_the_mesh_step(project, cfg), "production")
    _source_run(project, "coarse")
    replayed = _replayed(project, frozen)

    again = _freeze(project, replayed, _read_by_the_mesh_step(project, replayed), "replay")

    written = tomllib.loads(again.read_text(encoding="utf-8"))["mesh"]["refinement_zone"]
    assert [zone["run"] for zone in written] == [first]


def test_a_replay_whose_source_run_is_gone_is_refused_with_its_cause(project: Path) -> None:
    _source_run(project, "coarse")
    cfg = _config(project, ZONE)
    frozen = _freeze(project, cfg, _read_by_the_mesh_step(project, cfg), "production")
    _source_run(project, "coarse")
    shutil.rmtree(project / "runs" / "coarse")
    replayed = _replayed(project, frozen)

    with pytest.raises(ConfigError, match="no run carries that sim_id") as excinfo:
        read_run_fields(project, replayed.mesh.refinement_zone)

    assert replayed.mesh.refinement_zone[0].run in str(excinfo.value)
    assert "needs that run to be still there" in str(excinfo.value)


def test_a_zone_accepts_a_full_sim_id_as_its_run() -> None:
    zone = RefinementZoneConfig.model_validate({**ZONE, "run": "a" * 32})

    assert zone.run == "a" * 32
    assert zone.describe().endswith(f"in run {'a' * 32}")


def test_a_zone_the_mesh_did_not_read_keeps_the_name(project: Path) -> None:
    cfg = _config(project, ZONE)

    frozen = _freeze(project, cfg, {}, "production")

    written = tomllib.loads(frozen.read_text(encoding="utf-8"))["mesh"]["refinement_zone"]
    assert written == [ZONE]


def test_only_the_zones_that_read_a_run_are_rewritten(project: Path) -> None:
    sim_id = "b" * 32
    cfg = _config(
        project,
        {"where": "height_above_stream", "below": 2.0, "cell_size": 25.0},
        {**ZONE, "run": "coarse.v1"},
        {"path": "layer.gpkg", "cell_size": 30.0},
    )
    ctx = SimpleNamespace(
        cfg=cfg, run_dir=project / "runs" / "x", setup=SimpleNamespace(domain=None)
    )
    ctx.run_dir.mkdir(parents=True)

    document = frozen_config_document(ctx, project, zone_runs={"coarse.v1": sim_id})

    zones = tomllib.loads(document)["mesh"]["refinement_zone"]
    assert [zone.get("run") for zone in zones] == [None, sim_id, None]
    assert zones[0]["where"] == "height_above_stream" and zones[2]["path"] == "layer.gpkg"


def _planned(source_run: str | None) -> RefinementZone:
    return RefinementZone(
        region=box(0.0, 0.0, 1.0, 1.0), cell_size_m=25.0, ramp_m=50.0, source_run=source_run
    )


def test_the_mesh_step_keeps_one_sim_id_per_reference() -> None:
    cfgs = [
        RefinementZoneConfig.model_validate(ZONE),
        RefinementZoneConfig.model_validate(
            {"where": "seepage", "above": 1.0, "run": "coarse", "cell_size": 25.0}
        ),
        RefinementZoneConfig.model_validate({**ZONE, "run": "other"}),
        RefinementZoneConfig.model_validate({"path": "layer.gpkg", "cell_size": 30.0}),
    ]
    zones = [_planned("1" * 32), _planned("1" * 32), _planned("2" * 32), _planned(None)]

    assert _zone_runs(cfgs, zones) == {"coarse": "1" * 32, "other": "2" * 32}


def test_the_mesh_step_keeps_nothing_when_the_planner_dropped_a_zone() -> None:
    cfgs = [
        RefinementZoneConfig.model_validate(ZONE),
        RefinementZoneConfig.model_validate({"path": "layer.gpkg", "cell_size": 30.0}),
    ]

    assert _zone_runs(cfgs, [_planned(None)]) == {}


def test_the_summary_of_the_mesh_step_carries_the_zone_runs(tmp_path: Path, monkeypatch) -> None:
    inputs = planning_inputs(grid_spec(10, 10, 100.0), refinement_zones=(_planned("3" * 32),))
    monkeypatch.setattr(mesh_module, "planning_inputs", lambda ctx, mesh_cfg: inputs)
    mesh = MeshConfig(engine="regular", refinement_zone=[ZONE])
    ctx = SimpleNamespace(
        cfg=SimpleNamespace(mesh=mesh),
        setup=SimpleNamespace(workspace=SimpleNamespace(project_root=tmp_path)),
    )

    step_mesh(ctx)

    assert ctx.setup.mesh_summary["zone_runs"] == {"coarse": "3" * 32}


def _identity(cfg: HydroModPyConfig) -> str | None:
    """The identity hash a run records and a retry compares."""
    return config_identity_hash(cfg)


def test_a_resume_of_the_frozen_config_keeps_the_identity_of_the_first_attempt(
    project: Path,
) -> None:
    _source_run(project, "coarse")
    cfg = _config(project, ZONE)
    recorded = _identity(cfg)
    first = open_run_store(project, "production", n_cells=4, config_hash=recorded)
    first.close()
    frozen = _freeze(project, cfg, _read_by_the_mesh_step(project, cfg), "frozen")
    _source_run(project, "coarse")

    replayed = _replayed(project, frozen)

    assert replayed.mesh.refinement_zone[0].run != "coarse"
    assert _identity(replayed) == recorded
    assert not _config_changed(first.run_dir, _identity(replayed)), "the retry resumes"


def test_a_new_run_from_the_bare_name_after_a_later_version_is_another_computation(
    project: Path,
) -> None:
    _source_run(project, "coarse")
    cfg = _config(project, ZONE)
    recorded = _identity(cfg)
    first = open_run_store(project, "production", n_cells=4, config_hash=recorded)
    first.close()
    _source_run(project, "coarse")

    assert _identity(cfg) != recorded
    assert _config_changed(first.run_dir, _identity(cfg)), "the retry starts over"

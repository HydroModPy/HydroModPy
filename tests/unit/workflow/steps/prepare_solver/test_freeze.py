"""The ``config.toml`` and ``config.resolved.toml`` a run freezes, and the earlier runs its refinement zones read."""

from __future__ import annotations

import shutil
import tomllib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.data.loading.inputs import ResolvedInputs
from hydromodpy.mesh.planning.refinement_zones import (
    CriterionInputs,
    load_refinement_zones,
)
from hydromodpy.results.run.field_envelope import read_run_fields
from hydromodpy.results.storage.contract import (
    RUN_CONFIG_FILENAME,
    RUN_RESOLVED_CONFIG_FILENAME,
)
from hydromodpy.results.storage.sealing import seal_completed
from hydromodpy.workflow.solution_key import request_id_of
from hydromodpy.workflow.steps.mesh import zone_runs
from hydromodpy.workflow.steps.prepare_solver.freeze import (
    freeze_run_config,
    frozen_config_document,
    write_claim_config,
)
from hydromodpy.workflow.steps.prepare_solver.restart import (
    source_state_digests,
    zone_run_ids,
)
from tests._helpers.mesh_cases import grid_spec
from tests._helpers.run_stores import open_run_store

# The frozen ``config.toml`` keeps what the run was given and validates again: a replay by
# ``hmp run --resume`` (the file) or by ``hmp catalog rerun`` (the snapshot) gives back the
# configuration of the run. The soil section refuses ``recharge.values``, and soil mode reads
# ``surface_offset`` only when the file wrote it, so neither is spelled out as a default.

PROJECT = """\
[workflow]
mode = "simulation"

[simulation]
name = "soil_frozen"

[simulation.time]
start_datetime = "2001-01-01"
end_datetime = "2001-04-10"
step_value = "1 day"

[[simulation.process]]
id = "flow_main"
kind = "flow"
solvers = ["modflow6"]

[geographic]
source_mode = "synthetic"
crs_project = "EPSG:2154"

[geographic.synthetic]
case_id = "soil_frozen"

[geographic.synthetic.grid]
length_x = "1000 m"
length_y = "1000 m"
nx = 20
ny = 20

[geographic.synthetic.topography]
kind = "linear"
base_elevation = 20.0
right_to_left_amplitude = 5.0

[domain.depth_model]
kind = "constant_thickness"
thickness = "20 m"

[data]
types = ["precipitation", "etp"]

[[data.precipitation.sources]]
source = "file"
path = "../../data/precipitation/precipitation.nc"

[[data.etp.sources]]
source = "file"
path = "../../data/etp/etp.nc"

[flow]
param_list = ["K", "Sy", "Ss"]
first_period_steady = false

[flow.param.K.field]
kind = "homogeneous"
unit = "m/s"
value = 1e-5

[flow.param.Sy.field]
kind = "homogeneous"
unit = "-"
value = 0.1

[flow.param.Ss.field]
kind = "homogeneous"
unit = "m-1"
value = 1e-5

[flow.sinks_sources.recharge.soil]
ru = "150 mm"
spinup = "none"
transit_time = "5 days"

[flow.sinks_sources.etp]
extinction_depth = "2 m"

[flow.bc.drainage]

[display]
enabled = false
"""


def _project(root: Path, text: str = PROJECT) -> Path:
    for name in ("precipitation", "etp"):
        folder = root / "data" / name
        folder.mkdir(parents=True)
        (folder / f"{name}.nc").write_bytes(b"x")
    project = root / "projects" / "soil"
    project.mkdir(parents=True)
    (project / "project.toml").write_text(text, encoding="utf-8")
    return project


def _identity(cfg: HydroModPyConfig, project: Path | None = None) -> str:
    """The request id of *cfg*, with the state of each earlier run it reads when it reads one."""
    states = None if project is None else source_state_digests(cfg, project) or None
    return request_id_of(cfg, ResolvedInputs(), search=True, source_states=states)


def _frozen(project: Path, cfg: HydroModPyConfig | None = None) -> tuple[HydroModPyConfig, Path]:
    cfg = cfg or HydroModPyConfig.from_toml(project / "project.toml")
    run_dir = project / "runs" / "soil_frozen"
    run_dir.mkdir(parents=True)
    ctx = SimpleNamespace(cfg=cfg, run_dir=run_dir, setup=SimpleNamespace(domain=None))
    path = run_dir / "config.toml"
    path.write_text(frozen_config_document(ctx, project), encoding="utf-8")
    return cfg, path


def _replays(project: Path, frozen: Path) -> tuple[HydroModPyConfig, HydroModPyConfig]:
    snapshot = tomllib.loads(frozen.read_text(encoding="utf-8"))
    snapshot.setdefault("workspace", {})["project_root"] = str(project)
    return HydroModPyConfig.from_toml(frozen), HydroModPyConfig.from_snapshot(snapshot)


def test_soil_etp_offset_stays_unwritten(tmp_path: Path) -> None:
    project = _project(tmp_path)

    _, frozen = _frozen(project)

    for replayed in _replays(project, frozen):
        etp = replayed.flow.sinks_sources.etp
        assert "extinction_depth" in etp.model_fields_set
        assert "surface_offset" not in etp.model_fields_set


def test_inferred_data_type_not_frozen(tmp_path: Path) -> None:
    # A file cannot list a type without its section, and the planner infers it again.
    project = _project(tmp_path)
    cfg = HydroModPyConfig.from_toml(project / "project.toml")
    cfg.data = cfg.data.with_resolved_types([*cfg.data.types, "oceanic"])

    _, frozen = _frozen(project, cfg)

    assert "oceanic" not in tomllib.loads(frozen.read_text(encoding="utf-8"))["data"]["types"]
    assert all(replay.data.oceanic is None for replay in _replays(project, frozen))


# The frozen config names the run a refinement zone read by its sim_id, not by its name. A bare
# name is the latest version, so after a ``.v2`` a replay would read it and draw another mesh.

CELL = 100.0

GRID = grid_spec(8, 8, 25.0)


ZONE = {"where": "watertable_depth", "below": 0.5, "run": "coarse", "cell_size": 25.0}


def _source_run(project: Path, name: str, *, head: float = 99.75) -> str:
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
        handle.write_field_stack("head", np.array([[[head, 95.0, 95.0, 95.0]]]).transpose(0, 2, 1))
    finally:
        handle.close()
    seal_completed(store)
    return sim_id


def _config(project: Path, *zones: dict) -> HydroModPyConfig:
    return HydroModPyConfig.from_dict(
        {
            "workflow": {"mode": "simulation"},
            "site": {"name": "site_a"},
            "geographic": {
                "catchment": {"kind": "dem"},
                "river_network": {"threshold_area_km2": 0.5},
            },
            "data": {
                "types": ["dem"],
                "dem": {"sources": [{"source": "file", "path": "inputs/dem.tif"}]},
            },
            "mesh": {
                "engine": "voronoi",
                "families": {"rivers": "none"},
                "refinement_zone": list(zones),
            },
        },
        base_dir=project,
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
    return zone_runs(zones, planned)


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
    freeze_run_config(ctx, store=store)
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


def test_replay_freezes_the_same_sim_id(project: Path) -> None:
    first = _source_run(project, "coarse")
    cfg = _config(project, ZONE)
    frozen = _freeze(project, cfg, _read_by_the_mesh_step(project, cfg), "production")
    _source_run(project, "coarse")
    replayed = _replayed(project, frozen)

    again = _freeze(project, replayed, _read_by_the_mesh_step(project, replayed), "replay")

    written = tomllib.loads(again.read_text(encoding="utf-8"))["mesh"]["refinement_zone"]
    assert [zone["run"] for zone in written] == [first]


def test_replay_without_source_run_refused(project: Path) -> None:
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


def test_only_run_zones_rewritten(project: Path) -> None:
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


def test_same_state_same_request_id(project: Path) -> None:
    _source_run(project, "coarse")
    cfg = _config(project, ZONE)
    recorded = _identity(cfg, project)

    _source_run(project, "coarse")

    assert _identity(cfg, project) == recorded


def test_other_state_other_request_id(
    project: Path,
) -> None:
    _source_run(project, "coarse")
    cfg = _config(project, ZONE)
    recorded = _identity(cfg, project)

    _source_run(project, "coarse", head=99.5)

    assert _identity(cfg, project) != recorded, "the retry starts over"


# The claim freezes what the run was given, and the step that opens it freezes what it resolved.


def test_claim_freezes_the_run_it_reads(project: Path) -> None:
    sim_id = _source_run(project, "coarse")
    cfg = _config(project, ZONE)
    run_dir = project / "runs" / "production.v2"
    run_dir.mkdir(parents=True)
    ctx = SimpleNamespace(cfg=cfg, run_dir=run_dir)

    ids = zone_run_ids(cfg, project)
    path = write_claim_config(ctx, project_root=project, zone_runs=ids)

    document = tomllib.loads(path.read_text(encoding="utf-8"))
    assert ids == {"coarse": sim_id}
    assert document["mesh"]["refinement_zone"] == [{**ZONE, "run": sim_id}]
    assert document["simulation"]["name"] == "production", (
        "the name of the run, without its version"
    )
    assert not (run_dir / RUN_RESOLVED_CONFIG_FILENAME).exists()
    assert sorted(entry.name for entry in run_dir.iterdir()) == [RUN_CONFIG_FILENAME]


def test_zone_without_sealed_run_unchanged(project: Path) -> None:
    cfg = _config(project, ZONE)

    assert zone_run_ids(cfg, project) == {}


def test_open_step_keeps_the_claimed_config(project: Path) -> None:
    _source_run(project, "coarse")
    cfg = _config(project, ZONE)
    store = open_run_store(project, "production", n_cells=4)
    claimed = "# written at the claim\n"
    (store.run_dir / RUN_CONFIG_FILENAME).write_text(claimed, encoding="utf-8")
    ctx = SimpleNamespace(
        cfg=cfg,
        run_dir=store.run_dir,
        loaded_data=None,
        setup=SimpleNamespace(domain=None, flow=None, mesh_summary={}),
    )

    freeze_run_config(ctx, store=store)
    store.close()

    assert (store.run_dir / RUN_CONFIG_FILENAME).read_text(encoding="utf-8") == claimed
    assert (store.run_dir / RUN_RESOLVED_CONFIG_FILENAME).is_file()

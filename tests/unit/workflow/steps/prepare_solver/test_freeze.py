"""The frozen configuration of a run."""

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
from hydromodpy.mesh.mesh_config import MeshConfig
from hydromodpy.mesh.planning.refinement_zones import (
    CriterionInputs,
    RefinementZone,
    load_refinement_zones,
)
from hydromodpy.mesh.refinement_config import RefinementZoneConfig
from hydromodpy.results.catalog.registration import config_identity_hash
from hydromodpy.results.run.field_envelope import read_run_fields
from hydromodpy.results.storage.attempt import _config_changed
from hydromodpy.results.storage.contract import RUN_CONFIG_FILENAME
from hydromodpy.results.storage.sealing import seal_completed
from hydromodpy.workflow.steps import mesh as mesh_module
from hydromodpy.workflow.steps.mesh import step_mesh, zone_runs
from hydromodpy.workflow.steps.prepare_solver.freeze import (
    freeze_run_config,
    frozen_config_document,
    portable_config_document,
)
from tests._helpers.mesh_cases import grid_spec, planning_inputs
from tests._helpers.run_stores import open_run_store
from tests._helpers.sealed_runs import sealed_search

# --- test_a_soil_run_freezes_a_config_that_replays ---
# A soil run freezes a configuration that validates again, into the one it ran.
#
# The frozen ``config.toml`` used to spell out every default. Beside
# ``[flow.sinks_sources.recharge.soil]`` that wrote ``recharge.values = 0.0``, a
# key the soil section refuses when a file writes it, so every soil run stopped
# at ``prepare_solver``. It also wrote the ETP ``surface_offset``, which soil
# mode reads only when the file wrote it: a replay would have put the EVT surface
# 2 m below the drains instead of on them. The frozen document keeps what the
# run was given, and both replays (``hmp run --resume`` reads the file,
# ``hmp catalog rerun`` the snapshot) give back the configuration of the run.

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
active_sinks_sources = ["recharge", "etp"]
active_bc = ["drainage"]
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

[display]
enabled = false
"""


OFFSET_WRITTEN = PROJECT.replace(
    'extinction_depth = "2 m"\n', 'extinction_depth = "2 m"\nsurface_offset = "2.0 m"\n'
)


def _project(root: Path, text: str = PROJECT) -> Path:
    for name in ("precipitation", "etp"):
        folder = root / "data" / name
        folder.mkdir(parents=True)
        (folder / f"{name}.nc").write_bytes(b"x")
    project = root / "projects" / "soil"
    project.mkdir(parents=True)
    (project / "project.toml").write_text(text, encoding="utf-8")
    return project


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


def _settings(cfg: HydroModPyConfig) -> dict:
    return cfg.model_dump(mode="json", exclude={"workspace"})


def test_the_frozen_config_of_a_soil_run_replays_into_the_run_config(tmp_path: Path) -> None:
    project = _project(tmp_path)

    cfg, frozen = _frozen(project)

    assert (
        "values"
        not in tomllib.loads(frozen.read_text(encoding="utf-8"))["flow"]["sinks_sources"][
            "recharge"
        ]
    )
    for replayed in _replays(project, frozen):
        assert _settings(replayed) == _settings(cfg)
        recharge = replayed.flow.sinks_sources.recharge
        assert recharge.soil is not None
        assert "values" not in recharge.model_fields_set


def test_the_soil_etp_offset_stays_unwritten_on_replay(tmp_path: Path) -> None:
    project = _project(tmp_path)

    _, frozen = _frozen(project)

    for replayed in _replays(project, frozen):
        etp = replayed.flow.sinks_sources.etp
        assert "extinction_depth" in etp.model_fields_set
        assert "surface_offset" not in etp.model_fields_set


def test_an_offset_written_at_its_default_is_another_computation(tmp_path: Path) -> None:
    """Under a soil reservoir the key gives 2 m and no key gives 0 m, so one identity lied."""
    silent = HydroModPyConfig.from_toml(_project(tmp_path / "a") / "project.toml")
    written = HydroModPyConfig.from_toml(_project(tmp_path / "b", OFFSET_WRITTEN) / "project.toml")

    assert "surface_offset" in written.flow.sinks_sources.etp.model_fields_set
    assert "surface_offset" not in silent.flow.sinks_sources.etp.model_fields_set
    assert config_identity_hash(silent) != config_identity_hash(written)


@pytest.mark.parametrize("text", [PROJECT, OFFSET_WRITTEN], ids=["no-key", "key-at-its-default"])
@pytest.mark.parametrize(
    "changes", [{}, {"flow.param.K.field.value": 3.3e-3}], ids=["as-written", "with-an-override"]
)
def test_the_frozen_file_reads_back_to_the_identity_of_the_run(
    tmp_path: Path, text: str, changes: dict
) -> None:
    """What ``hmp run --resume`` compares: the identity of the file against the first attempt."""
    project = _project(tmp_path, text)
    base = HydroModPyConfig.from_toml(project / "project.toml")
    cfg = base.with_changes(changes) if changes else base

    _, frozen = _frozen(project, cfg)

    if changes:
        assert config_identity_hash(cfg) != config_identity_hash(base)
    for replay in _replays(project, frozen):
        assert config_identity_hash(replay) == config_identity_hash(cfg)


def test_an_inferred_data_type_stays_out_of_the_frozen_file(tmp_path: Path) -> None:
    """A file cannot list a type without its section, and the planner infers it again."""
    project = _project(tmp_path)
    cfg = HydroModPyConfig.from_toml(project / "project.toml")
    cfg.data = cfg.data.with_resolved_types([*cfg.data.types, "oceanic"])

    _, frozen = _frozen(project, cfg)

    assert "oceanic" not in tomllib.loads(frozen.read_text(encoding="utf-8"))["data"]["types"]
    assert all(replay.data.oceanic is None for replay in _replays(project, frozen))


# --- test_the_frozen_config_reads_in_any_workspace ---
# The frozen ``config.toml`` of a run names its inputs so that any copy of the workspace reads it.
#
# A file of the workspace ``data/`` is written relative to the project root
# (``../../data/<variable>/...``), a file of the project relative to it: no path
# of the machine, and no bare name, which a file no longer resolves. Read back
# from the project root, in the workspace it was frozen in or in another one
# holding the same data, the configuration points at the same files.

WORKSPACE_PROJECT = """\
[site]
name = "nancon"

[geographic]
crs_project = "EPSG:2154"

[geographic.catchment]
kind = "from_outlet_coord"
x_outlet = 389285.9
y_outlet = 6816518.7
snap_dist = "150 m"
buff_area = "10%"

[data]
types = ["dem", "hydrography", "hydrometry"]

[[data.dem.sources]]
source = "file"
path = "../../data/dem/DEM_armorican_massif.tif"

[[data.hydrography.sources]]
source = "file"
path = "../../data/hydrography/nancon_stream_network.gpkg"

[[data.hydrometry.sources]]
source = "file"
path = "../../data/hydrometry"
station_ids = ["NANCON"]
"""


def _workspace(root: Path) -> Path:
    for relative in (
        "data/dem/DEM_armorican_massif.tif",
        "data/hydrography/nancon_stream_network.gpkg",
    ):
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_bytes(b"x")
    (root / "data" / "hydrometry").mkdir(parents=True)
    project = root / "projects" / "nancon"
    project.mkdir(parents=True)
    (project / "project.toml").write_text(WORKSPACE_PROJECT, encoding="utf-8")
    return project


def _frozen_in_workspace(project: Path) -> Path:
    cfg = HydroModPyConfig.from_toml(project / "project.toml")
    run_dir = project / "runs" / "nancon"
    run_dir.mkdir(parents=True)
    path = run_dir / "config.toml"
    path.write_text(portable_config_document(cfg, run_dir, project), encoding="utf-8")
    return path


def test_the_frozen_config_names_its_inputs_by_their_portable_form(tmp_path: Path) -> None:
    project = _workspace(tmp_path / "laptop")

    frozen = _frozen_in_workspace(project)

    text = frozen.read_text(encoding="utf-8")
    assert str(tmp_path) not in text
    payload = tomllib.loads(text)
    sources = payload["data"]
    assert sources["dem"]["sources"][0]["path"] == "../../data/dem/DEM_armorican_massif.tif"
    assert (
        sources["hydrography"]["sources"][0]["path"]
        == "../../data/hydrography/nancon_stream_network.gpkg"
    )
    assert sources["hydrometry"]["sources"][0]["path"] == "../../data/hydrometry"


def test_another_workspace_reads_the_frozen_config_on_its_own_data(
    tmp_path: Path, monkeypatch
) -> None:
    frozen = _frozen_in_workspace(_workspace(tmp_path / "laptop"))
    other = _workspace(tmp_path / "cluster" / "ws")
    copied = other / "runs" / "nancon" / "config.toml"
    copied.parent.mkdir(parents=True)
    shutil.copy2(frozen, copied)
    monkeypatch.chdir(tmp_path)

    from_file = HydroModPyConfig.from_toml(copied)
    snapshot = tomllib.loads(copied.read_text(encoding="utf-8"))
    snapshot.setdefault("workspace", {})["project_root"] = str(other)
    from_snapshot = HydroModPyConfig.from_snapshot(snapshot)

    data = (tmp_path / "cluster" / "ws" / "data").resolve()
    for cfg in (from_file, from_snapshot):
        assert Path(cfg.data.dem.sources[0].path) == data / "dem" / "DEM_armorican_massif.tif"
        assert Path(cfg.data.hydrometry.sources[0].path) == data / "hydrometry"
        assert Path(cfg.data.hydrography.sources[0].path) == data / "hydrography" / (
            "nancon_stream_network.gpkg"
        )


# --- test_a_frozen_config_pins_the_run_a_refinement_zone_reads ---
# The frozen config names the run a refinement zone read by its sim_id, not by its name.
#
# A zone that reads an earlier run writes ``run = "<name>"``, and a bare name is
# the latest version of that run. After a ``.v2`` of the first run, a replay
# (``hmp catalog rerun`` reads the frozen snapshot, ``hmp run --resume`` the
# frozen file) would read the ``.v2`` and draw another mesh. The mesh step keeps
# the sim_id each zone read, and the freeze writes it in place of the name.

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
    return HydroModPyConfig.from_dict(
        {
            "workflow": {"mode": "simulation"},
            "workspace": {"project_root": str(project)},
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

"""A soil run freezes a configuration that validates again, into the one it ran.

The frozen ``config.toml`` used to spell out every default. Beside
``[flow.sinks_sources.recharge.soil]`` that wrote ``recharge.values = 0.0``, a
key the soil section refuses when a file writes it, so every soil run stopped
at ``prepare_solver``. It also wrote the ETP ``surface_offset``, which soil
mode reads only when the file wrote it: a replay would have put the EVT surface
2 m below the drains instead of on them. The frozen document keeps what the
run was given, and both replays (``hmp run --resume`` reads the file,
``hmp catalog rerun`` the snapshot) give back the configuration of the run.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.config import HydroModPyConfig
from hydromodpy.results.catalog.registration import config_identity_hash
from hydromodpy.workflow.steps.prepare_solver.dispatch import frozen_config_document
from tests._helpers.sealed_runs import sealed_search

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
type = "flow"
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
source = "custom"
path = "precipitation.nc"

[[data.etp.sources]]
source = "custom"
path = "etp.nc"

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

"""A run with a soil reservoir passes ``prepare_solver`` and replays from its frozen config.

Every run with ``[flow.sinks_sources.recharge.soil]`` stopped at
``prepare_solver``: the frozen configuration spelled out every default,
``recharge.values = 0.0`` among them, and the soil section refuses a rate
written beside it. Here a synthetic 1 km square catchment on a 2 x 2 grid of
daily rain and ETP runs 100 days under MODFLOW 6 in a disposable workspace,
then ``hmp catalog rerun`` replays it from its ``config.toml``: the replay
freezes the same configuration and gives the same heads, to the 16-bit
rounding of the stored fields.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr
import zarr

from tests.e2e._step1_minimal import disposable_env, hmp

pytestmark = pytest.mark.e2e

FIELD_PRECISION_RTOL = 2.0**-10
"""Relative step of a float32 rounded to 16 significant bits (see tests/TOLERANCES.md)."""

RUN_NAME = "soil_replay"
DAYS = pd.date_range("2001-01-01", periods=100, freq="D")
SAFRAN_X = np.array([250.0, 750.0])
SAFRAN_Y = np.array([250.0, 750.0])

PROJECT = f"""\
[workflow]
mode = "simulation"

[simulation]
name = "{RUN_NAME}"

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
case_id = "{RUN_NAME}"

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
path = "precipitation.nc"

[[data.etp.sources]]
source = "file"
path = "etp.nc"

[flow]
param_list = ["K", "Sy", "Ss"]
first_period_steady = false

[flow.ic]
kind = "steady_state"

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

[flow.bc.drainage]

[flow.sinks_sources.recharge.soil]
ru = "150 mm"
spinup = "none"
transit_time = "5 days"

[flow.sinks_sources.etp]
extinction_depth = "2 m"

[display]
enabled = false
"""


def _forcing(path: Path, name: str, values: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    dataset = xr.Dataset(
        {name: (("time", "y", "x"), values)},
        coords={"time": DAYS.values, "y": SAFRAN_Y, "x": SAFRAN_X},
    )
    dataset.attrs["crs"] = "EPSG:2154"
    dataset[name].attrs["nodata"] = -9999.0
    dataset.to_netcdf(path)


def _workspace(root: Path) -> Path:
    rng = np.random.default_rng(0)
    rain = rng.gamma(shape=0.6, scale=4.0 / 0.6, size=(len(DAYS), 2, 2))
    curve = 2.0 + np.sin(2.0 * np.pi * np.arange(len(DAYS)) / 40.0)
    etp = np.broadcast_to(curve[:, None, None], (len(DAYS), 2, 2)).copy()
    _forcing(root / "data" / "precipitation" / "precipitation.nc", "precipitation", rain)
    _forcing(root / "data" / "etp" / "etp.nc", "etp", etp)
    project = root / "projects" / "soil"
    project.mkdir(parents=True)
    (project / "project.toml").write_text(PROJECT, encoding="utf-8")
    return project


def _heads(run_dir: Path) -> np.ndarray:
    root = zarr.open_group(str(run_dir / "fields.zarr"), mode="r", use_consolidated=False)
    return np.asarray(root["head"])


def _ok(result, what: str) -> None:
    assert result.returncode == 0, f"{what}: {result.stderr[-4000:]}"


def test_a_soil_run_replays_from_its_frozen_config(tmp_path: Path) -> None:
    env = disposable_env(tmp_path / "home")
    workspace = tmp_path / "ws"
    _ok(hmp("workspace", "init", str(workspace), cwd=tmp_path, env=env), "workspace init")
    project = _workspace(workspace)

    _ok(hmp("run", "project.toml", cwd=project, env=env), "run")
    source = project / "runs" / RUN_NAME
    frozen = tomllib.loads((source / "config.toml").read_text(encoding="utf-8"))
    assert "values" not in frozen["flow"]["sinks_sources"]["recharge"]

    _ok(hmp("catalog", "rerun", RUN_NAME, "-w", str(project), cwd=tmp_path, env=env), "rerun")

    replay = project / "runs" / f"{RUN_NAME}.v2"
    manifest = json.loads((replay / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["lineage"]["kind"] == "rerun"
    assert tomllib.loads((replay / "config.toml").read_text(encoding="utf-8")) == frozen
    np.testing.assert_allclose(_heads(replay), _heads(source), rtol=FIELD_PRECISION_RTOL)

"""persist_trial_series end to end: one real MF6 solve, two trials, two files.

No existing calibration test in the suite runs a few trials through a real
solver quickly: the calibration unit tests fake the solver entirely (the
scorer is exercised directly, as in ``test_persist_trial_series.py``), and the
only calibration test that runs real MODFLOW 6 end to end is the ``e2e`` /
``slow`` byte-identical promotion test on the full example 04 catchment. This
is the small, synthetic replacement: a six-cell steady hillslope (recharge in,
drainage out, the same well-posed pair ``test_twin_matching_stream_network_
modflow6.py`` uses), a grid search of two points on K, and a head output that
observes one station. The observed record and its cell are the two things a
synthetic project has no loader for, so they are monkeypatched exactly where
``test_observable_scoring.py`` already patches them for a unit test.

What this proves that the unit tests of the capture logic do not: the real
wiring, through ``run_calibration_core`` and the shared ``evaluator`` object,
across the ``ThreadPoolExecutor`` a ``parallel`` run dispatches trials on.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.metrics import composite
from hydromodpy.calibration.metrics.series import ObservedSeries
from hydromodpy.calibration.runners.cli_runner import run_calibration_core
from hydromodpy.calibration.runners.state import override_paths, space_from_config
from hydromodpy.calibration.runners.trial import prepare_trials
from hydromodpy.results.session_journal import sessions_dir_for
from hydromodpy.results.storage.contract import SESSION_TRIAL_SERIES_DIRNAME
from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary

STATION = "W1"
_CELL = (0, 0, 3)

_PROJECT_TOML = """\
[workflow]
mode = "simulation"

[simulation]
name = "persist_trial_series_probe"

[[simulation.process]]
id = "flow"
type = "flow"
solvers = ["modflow6"]

[workspace]
project_root = "{root}"

[geographic]
source_mode = "synthetic"
crs_project = "EPSG:2154"

[geographic.synthetic]
case_id = "persist_trial_series_probe"

[geographic.synthetic.grid]
length_x = "12 m"
length_y = "2 m"
nx = 6
ny = 1

[geographic.synthetic.topography]
kind = "linear"
base_elevation = 10.0
right_to_left_amplitude = 1.0

[domain.depth_model]
kind = "constant_thickness"
thickness = "5 m"

[flow]
flow_regime = "steady"
active_sinks_sources = ["recharge"]
active_bc = ["drainage"]
param_list = ["K"]

[flow.param.K.field]
kind = "homogeneous"
unit = "m/s"
value = 5e-6

[flow.ic]
type = "top"

[flow.bc.drainage]
application_domain = "top"
kind = "cauchy"
value = "0.0 m2/s"

[flow.sinks_sources.recharge]
first_clim = "mean"

[data]
types = ["recharge"]
inference_mode = "warn"

[[data.recharge.sources]]
source = "synthetic"
values = [0.8]
runoff_ratio = 0.0

[modflow6.sgrid.planar]
mode = "resample_to_shape"
nx = 6
ny = 1
resampling = "nearest"

[modflow6.sgrid.vertical]
nlay = 1

[display]
enabled = false
"""


@pytest.fixture
def project(tmp_path: Path) -> Path:
    import hydromodpy

    hydromodpy.bootstrap()
    config_path = tmp_path / "project.toml"
    config_path.write_text(_PROJECT_TOML.format(root=tmp_path.as_posix()), encoding="utf-8")
    return config_path


def _wire_the_station(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hand the single-metric route a station, the way a project's loader would.

    ``load_observed`` and ``resolve_station_cells`` both read
    ``ctx.loaded_data.piezometry``, which a synthetic project never loads
    (there is no ``[data.piezometry]`` source here, by design: the run is
    about the trial loop, not about reading a record off disk). Patched at
    the name ``composite.py`` imported, the same way ``test_observable_
    scoring.py`` wires a producer for its own unit tests.
    """
    observed = [ObservedSeries(station_id=STATION, variable="head", series=pd.Series([5.0]))]
    monkeypatch.setattr(composite, "load_observed", lambda ctx, variable: observed)
    monkeypatch.setattr(
        composite, "resolve_station_cells", lambda ctx, obs, **kwargs: {STATION: _CELL}
    )


@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.allow_subprocess
def test_two_trials_on_persist_trial_series_write_two_files(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ensure_solver_binary("mf6")
    _wire_the_station(monkeypatch)

    cfg = CalibrationConfig.model_validate(
        {
            "method": "grid",
            "method_options": {"points_per_dim": 2},
            "variable": "head",
            "objective": "rmse",
            "save_runs": "none",
            "persist_trial_series": True,
            # Both grid points in one batch, dispatched through the
            # ThreadPoolExecutor (engine.py, parallel > 1): this is what
            # actually exercises the thread-local capture under concurrency,
            # not just the sequential loop.
            "parallel": 2,
            "parameters": {
                "K": {
                    "bounds": [1e-6, 1e-4],
                    "transform": "log",
                    "path": "flow.param.K.field.value",
                }
            },
        }
    )
    space = space_from_config(cfg)
    trial_ctx = prepare_trials(project, override_paths=override_paths(cfg), parameter_space=space)

    report = run_calibration_core(
        cfg, trial_ctx, workspace=project.parent, space=space, cfg_path=project
    ).to_dict()

    assert report["n_iterations"] == 2
    session_dirs = sessions_dir_for(project.parent)
    assert len(list(session_dirs.iterdir())) == 1
    series_dir = next(session_dirs.iterdir()) / SESSION_TRIAL_SERIES_DIRNAME
    assert sorted(p.name for p in series_dir.iterdir()) == [
        "trial-000001.parquet",
        "trial-000002.parquet",
    ]
    table_1 = pd.read_parquet(series_dir / "trial-000001.parquet")
    table_2 = pd.read_parquet(series_dir / "trial-000002.parquet")
    # Both trials ran on different ThreadPoolExecutor workers and recorded
    # into their own thread-local sink. Each file holds exactly the one row
    # its own trial scored, with no row dropped, duplicated or picked up
    # from the other worker's thread.
    for table in (table_1, table_2):
        assert table["station"].tolist() == [STATION]
        assert table["output"].tolist() == ["head"]
    assert table_1["simulated"].iloc[0] != table_2["simulated"].iloc[0]

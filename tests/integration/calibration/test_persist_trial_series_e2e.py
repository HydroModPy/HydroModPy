"""persist_trial_series end to end: one real MF6 solve, two trials, two files.

No existing calibration test in the suite runs a few trials through a real
solver quickly: the calibration unit tests fake the solver entirely (the
scorer is exercised directly, as in ``test_metrics_trial_series_capture.py``), and the
only calibration test that runs real MODFLOW 6 end to end is the ``e2e`` /
``slow`` byte-identical promotion test on the full example 04 catchment. This
is the small, synthetic replacement: a six-cell steady hillslope (recharge in,
drainage out, the same well-posed pair ``test_twin_matching_stream_network_
modflow6.py`` uses), a grid search of two points on K, and a head output that
observes one station. The station is on disk, as a user writes it, because a
monkeypatch does not reach a worker process. The same search runs at
``parallel = 1`` and ``parallel = 2``, and the two must agree to the last digit.

What this proves that the unit tests of the capture logic do not: the real
wiring, through ``run_one_search`` and a worker process that solves. The same
case also runs three restarts side by side on one pool, and the MODFLOW 6 API
runner in a worker.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.persistence import CalibrationPersistence, PhaseContext
from hydromodpy.calibration.runners.cli_runner import run_one_search
from hydromodpy.calibration.runners.state import override_paths, space_from_config
from hydromodpy.calibration.runners.trial import prepare_trials
from hydromodpy.results.storage.contract import SESSION_TRIAL_SERIES_DIRNAME
from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary

STATION = "W1"

_PROJECT_TOML = """\
[workflow]
mode = "simulation"

[simulation]
name = "persist_trial_series_probe"

[simulation.time]
start_datetime = "2003-01-01 00:00:00"
end_datetime = "2003-01-02 00:00:00"
step_value = "1 day"
coverage_policy = "ignore"

[[simulation.process]]
id = "flow"
kind = "flow"
solvers = ["modflow6"]

[workspace]

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

[modflow6.runtime]
mf6_runner = "{runner}"

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
kind = "top"

[flow.bc.drainage]
application_domain = "top"
kind = "drain"
value = "0.0 m2/s"

[flow.sinks_sources.recharge]
first_clim = "mean"

[data]
types = ["recharge", "piezometry"]
inference_mode = "warn"

[[data.recharge.sources]]
source = "synthetic"
values = [0.8]

[data.piezometry]
[[data.piezometry.sources]]
source = "custom"
path = "{root}/piezometry"
default_crs = "EPSG:2154"
source_unit = "m"

[mesh.regular]
shape = [1, 6]

[domain.layers]
nlay = 1

[display]
enabled = false
"""


def _project(root: Path, runner: str) -> Path:
    """Write the synthetic project and its station on disk, the way a user would."""
    import hydromodpy

    hydromodpy.bootstrap()
    station = root / "piezometry"
    station.mkdir(parents=True)
    (station / "piezometry_custom_LOC.csv").write_text(f"id,x,y\n{STATION},7.0,1.0\n")
    days = pd.date_range("2003-01-01", periods=3, freq="D")
    record = pd.DataFrame({"datetime": days, "value": [5.0, 5.0, 5.0]})
    record.to_csv(station / f"piezometry_custom_{STATION}_D.csv", index=False)
    config_path = root / "project.toml"
    config_path.write_text(
        _PROJECT_TOML.format(root=root.as_posix(), runner=runner), encoding="utf-8"
    )
    return config_path


def _calibrate(
    root: Path, parallel: int, *, runner: str = "subprocess", **search: object
) -> tuple[dict, CalibrationPersistence]:
    """Run a search on K at one width, through the call the CLI makes, and return its answer."""
    project = _project(root, runner)
    cfg = CalibrationConfig.model_validate(
        {
            "method": "grid",
            "method_options": {"points_per_dim": 2},
            "variable": "head",
            "objective": "rmse",
            "save_runs": "none",
            "persist_trial_series": True,
            "parallel": parallel,
            "parameters": {
                "K": {
                    "bounds": [1e-6, 1e-4],
                    "search_space": "log",
                    "path": "flow.param.K.field.value",
                }
            },
            **search,
        }
    )
    space = space_from_config(cfg)
    trial_ctx = prepare_trials(project, override_paths=override_paths(cfg), parameter_space=space)
    session_dir = root / "sessions" / "probe"
    session_dir.mkdir(parents=True)
    persistence = CalibrationPersistence(session_dir)
    persistence.start_session(
        session_id="a" * 32,
        case_id="probe",
        site=None,
        project=root.name,
        config_hash="c" * 64,
        hydromodpy_version="2.0.0a5",
        method=cfg.method,
        cost_name="rmse",
        bounds={},
        windows={},
    )
    report, _ = run_one_search(
        cfg,
        trial_ctx,
        persistence=persistence,
        space=space,
        project_root=root,
        cfg_path=project,
        metric_fn=None,
        objective=None,
        phase=PhaseContext(),
    )
    return report.to_dict(), persistence


def _series(persistence: CalibrationPersistence) -> list[pd.DataFrame]:
    """Return the two files of the two trials of the grid."""
    series_dir = persistence.directory / SESSION_TRIAL_SERIES_DIRNAME
    assert sorted(p.name for p in series_dir.iterdir()) == [
        "trial-000001.parquet",
        "trial-000002.parquet",
    ]
    return [pd.read_parquet(series_dir / f"trial-00000{n}.parquet") for n in (1, 2)]


def _costs_of_each_restart(persistence: CalibrationPersistence) -> dict[int, list[float]]:
    """Return the costs the search read, by restart, in the order of its trials."""
    lines = [line for line in persistence.trials() if not line.speculative_unused]
    return {
        restart: [line.cost for line in lines if line.restart == restart]
        for restart in sorted({line.restart for line in lines})
    }


@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.allow_subprocess
def test_a_search_in_two_processes_gives_the_digits_of_a_search_in_one(tmp_path: Path) -> None:
    ensure_solver_binary("mf6")
    (report_one, session_one), (report_two, session_two) = (
        _calibrate(tmp_path / "one", 1),
        _calibrate(tmp_path / "two", 2),
    )
    tables_one, tables_two = _series(session_one), _series(session_two)

    assert report_one["n_trials"] == report_two["n_trials"] == 2
    for tables in (tables_one, tables_two):
        # Each file holds exactly the one row its own trial scored, with no row
        # dropped, duplicated or picked up from the other trial.
        for table in tables:
            assert table["station"].tolist() == [STATION]
            assert table["output"].tolist() == [f"head@{STATION}"]
        assert tables[0]["simulated"].iloc[0] != tables[1]["simulated"].iloc[0]
    # The same trial solved in this process and in a worker, to the last digit.
    for one, two in zip(tables_one, tables_two, strict=True):
        assert one["simulated"].tolist() == two["simulated"].tolist()
    assert report_one["best_cost"] == report_two["best_cost"]


@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.allow_subprocess
@pytest.mark.parametrize(
    ("runner", "search"),
    [
        pytest.param(
            "subprocess",
            {
                "method": "scipy_nelder_mead",
                "method_options": {},
                "max_trials": 4,
                "seed": 7,
                "uncertainty": {"method": "multistart", "restarts": 3},
            },
            id="three_restarts_on_one_pool",
        ),
        pytest.param(
            "api",
            {"method_options": {"points_per_dim": 4}},
            marks=pytest.mark.skipif(
                importlib.util.find_spec("modflowapi") is None, reason="needs modflowapi"
            ),
            id="the_api_runner_in_a_worker",
        ),
    ],
)
def test_the_costs_of_a_search_in_workers_are_those_of_a_search_in_one(
    tmp_path: Path, runner: str, search: dict
) -> None:
    ensure_solver_binary("mf6")
    in_one = _calibrate(tmp_path / "one", 1, runner=runner, **search)
    in_two = _calibrate(tmp_path / "two", 2, runner=runner, **search)

    assert _costs_of_each_restart(in_one[1]) == _costs_of_each_restart(in_two[1])
    assert in_one[0]["best_cost"] == in_two[0]["best_cost"]

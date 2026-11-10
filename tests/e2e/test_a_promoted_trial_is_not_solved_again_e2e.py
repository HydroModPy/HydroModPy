"""End-to-end: a promoted trial is the run a replay writes, without a second solve.

A calibration keeps the solver folder of each trial it may promote, and the
promotion goes on from extraction on that folder instead of solving again. This
runs the same small calibration twice on real MODFLOW 6, in two workspaces: once
as shipped, once with every promotion forced back to a replay. Every promoted
run must come out the same both ways:

* the Zarr arrays, bit for bit;
* the Parquet tables, bit for bit apart from ids, timestamps and durations, and
  the configuration snapshot apart from the ``[workspace]`` paths, which name
  the scratch folder of the process;
* the metrics, apart from the solve time of the run;
* the list of figures.

The model is example 04 (the Nancon catchment) cut to one monthly transient
year on a 30 x 30 grid, with K on two fixed values and every trial promoted:
the best to ``runs/kept_solve/``, the other to ``sessions/kept_solve/trials/``.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from tests.regression.golden_utils import assert_required_executables

_REPO_ROOT = Path(__file__).resolve().parents[2]
_EXAMPLE = _REPO_ROOT / "examples" / "projects" / "04_streamflow_intermittence_in_transient"

_CALIBRATION = """\
base_config = "project.toml"

# The exports of project.toml name October 2002, outside this record.
export__delete = true

[simulation]
name = "kept_solve"
description = "One monthly transient year, K on two values, every trial promoted."

[simulation.time]
start_datetime = "2000-01-01"
end_datetime = "2000-12-31"
step_value = "1 month"

# project.toml scores 2001-2002, outside this one-year record.
[metrics]
window = { start = "2000-02-01", end = "2000-12-31" }

[mesh.regular]
shape = [30, 30]

[calibration]
save_runs = "all"

[calibration.parameters.K]
bounds = [1e-5, 1e-4]

[calibration.outputs.hydrograph]
support = "point"
variable = "discharge"
observes = "NANCON"

[[calibration.objective_blocks]]
name = "hydrograph"
metric = "nse"
uses_outputs = ["hydrograph"]

[[calibration.phases]]
name = "k_grid"
parameters = ["K"]
regime = "transient"
objective_blocks = ["hydrograph"]
method = "grid"
max_trials = 2
method_options = { points_per_dim = 2 }
parallel = 2

[display]
on_error = "warn"
time = "2000-10-15"
figures = ["hydrograph_sim_obs", "seepage_map", "flux_timeseries", "parameter_cost_profile"]
"""

# Columns that name the run or the moment it was written, never its numbers.
_IDENTITY_COLUMNS = frozenset(
    {
        "sim_id",
        "attempt_id",
        "rel_dir",
        "valid_from",
        "created_at",
        "updated_at",
        "started_at",
        "ended_at",
        "duration_s",
        "config_hash",
        "config_snapshot",
        "config_toml",
        "session_id",
        "calibrated_by_session_id",
    }
)
_SOLVE_TIME_METRIC = "flow_solve_time_seconds"


def _project(root: Path) -> Path:
    project = root / "projects" / "p"
    project.mkdir(parents=True)
    (root / "data").symlink_to(_REPO_ROOT / "examples" / "data", target_is_directory=True)
    shutil.copy(_EXAMPLE / "project.toml", project / "project.toml")
    (project / "calib.toml").write_text(_CALIBRATION, encoding="utf-8")
    return project


def _calibrate(project: Path, monkeypatch: pytest.MonkeyPatch, *, replay: bool) -> None:
    import hydromodpy as hmp
    from hydromodpy.calibration.runners.kept_solves import TrialSolveRetention

    with monkeypatch.context() as patch:
        patch.chdir(project)
        if replay:
            patch.setattr(
                TrialSolveRetention,
                "take",
                lambda self, trial_id: (None, "forced back to a replay for the comparison"),
            )
        hmp.calibrate(project / "calib.toml")


def _arrays(store: Path) -> dict[str, np.ndarray]:
    import zarr

    found: dict[str, np.ndarray] = {}

    def _walk(group, prefix: str) -> None:
        for name, array in group.arrays():
            found[f"{prefix}{name}"] = np.asarray(array[...])
        for name, child in group.groups():
            _walk(child, f"{prefix}{name}/")

    _walk(zarr.open_group(str(store), mode="r"), "")
    return found


def _without_workspace(snapshot: str) -> dict:
    payload = json.loads(snapshot)
    payload.pop("workspace", None)
    return payload


def _assert_same_tables(kept: Path, replayed: Path) -> None:
    import pyarrow.parquet as pq

    names = sorted(path.name for path in kept.glob("*.parquet"))
    assert names == sorted(path.name for path in replayed.glob("*.parquet"))
    assert names, f"no table under {kept}"
    for name in names:
        left = pq.read_table(kept / name)
        right = pq.read_table(replayed / name)
        assert left.schema.names == right.schema.names, name
        assert left.num_rows == right.num_rows, name
        if name == "metrics.parquet":
            # The time of the solve is in profile.json: no run writes it as a metric, so
            # the tables of the two runs can be compared in full.
            assert _SOLVE_TIME_METRIC not in left.column("metric").to_pylist()
            assert left.column("metric").to_pylist() == right.column("metric").to_pylist()
        for column in left.column_names:
            if column in _IDENTITY_COLUMNS:
                continue
            assert left.column(column).equals(right.column(column)), f"{name}:{column}"
        if "config_snapshot" in left.column_names:
            assert _without_workspace(left.column("config_snapshot")[0].as_py()) == (
                _without_workspace(right.column("config_snapshot")[0].as_py())
            )


def _promoted_runs(project: Path) -> list[Path]:
    """The calibrated run and the kept trials, as the session journal names them."""
    from hydromodpy.results.session.journal import read_trials

    lines = read_trials(project / "sessions" / "kept_solve")
    cases = [line.only_case for line in lines]
    rel_dirs = sorted(case.rel_dir for case in cases if case is not None and case.rel_dir)
    return [project / rel_dir for rel_dir in rel_dirs]


@pytest.mark.e2e
@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.slow
def test_a_promoted_trial_is_the_run_a_replay_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert_required_executables(
        require_modflow=False,
        require_modflow6=True,
        require_modpath=False,
        require_mt3dms=False,
    )
    kept_project = _project(tmp_path / "kept")
    replay_project = _project(tmp_path / "replay")

    _calibrate(kept_project, monkeypatch, replay=False)
    _calibrate(replay_project, monkeypatch, replay=True)

    kept_runs = _promoted_runs(kept_project)
    replay_runs = _promoted_runs(replay_project)
    assert [run.relative_to(kept_project) for run in kept_runs] == [
        Path("runs/kept_solve"),
        Path("sessions/kept_solve/trials/0001"),
    ] or [run.relative_to(kept_project) for run in kept_runs] == [
        Path("runs/kept_solve"),
        Path("sessions/kept_solve/trials/0002"),
    ]
    assert [run.relative_to(kept_project) for run in kept_runs] == [
        run.relative_to(replay_project) for run in replay_runs
    ]
    for kept_run, replay_run in zip(kept_runs, replay_runs, strict=True):
        kept_lineage = json.loads((kept_run / "manifest.json").read_text())["lineage"]
        replay_lineage = json.loads((replay_run / "manifest.json").read_text())["lineage"]
        assert kept_lineage["trial"] == replay_lineage["trial"]
        assert kept_lineage["kind"] == replay_lineage["kind"]

        kept_arrays = _arrays(kept_run / "fields.zarr")
        replay_arrays = _arrays(replay_run / "fields.zarr")
        assert kept_arrays.keys() == replay_arrays.keys()
        assert "head" in kept_arrays
        for key, array in kept_arrays.items():
            other = replay_arrays[key]
            assert (array.dtype, array.shape) == (other.dtype, other.shape), key
            assert array.tobytes() == other.tobytes(), key

        _assert_same_tables(kept_run / "tables.parquet", replay_run / "tables.parquet")

        figures = sorted(path.name for path in (kept_run / "figures").iterdir())
        assert figures
        assert figures == sorted(path.name for path in (replay_run / "figures").iterdir())

    # Nothing of the session is left in the run scratch.
    assert not (kept_project / ".hmp" / "scratch").exists()

"""A calibration whose trials rerun the previous one equals the same calibration that builds.

The sessions of the two scenario variants ``calage`` (K, steady) and ``calage_sy``
(Sy, transient) are played twice in this process. The first time ``rerun`` of the
MODFLOW 6 adapter works as shipped, so the trials after the first go through it. The
second time ``rerun`` is replaced by a function that returns ``None``, which the
runner reads as "build instead", so every trial builds its model.

Bit-identical means that the costs, their components, the scored series of each
trial and the best trial are equal, and that the promoted run holds equal fields and
equal numbers in its tables. The comparison of the run is the one of ``refhash/1``:
floats as float64, ``-0.0`` as ``0.0``, one NaN, and no column that carries an
identity, a date or a duration.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
import zarr

import hydromodpy as hmp
from hydromodpy.results.session.journal import read_trials
from hydromodpy.results.session.trial_series import read_trial_series
from hydromodpy.solver.modflow6.adapter import Modflow6FlowAdapter
from tests.scenarios.factory import island_files, write_project
from tests.scenarios.launcher import isolated_env, link_binaries

pytestmark = [
    pytest.mark.integration,
    pytest.mark.mf6,
    pytest.mark.binary,
    pytest.mark.allow_subprocess,
]

NEEDS = ("mf6", "libmf6.so")

IDENTITY_COLUMNS = frozenset(
    {
        "sim_id",
        "parent_sim_id",
        "attempt_id",
        "session_id",
        "calibrated_by_session_id",
        "created_at",
        "started_at",
        "ended_at",
        "duration_s",
        "valid_from",
        "fetched_at",
    }
)


def _canonical(values: np.ndarray) -> np.ndarray:
    """Return an array the way ``refhash/1`` reads it: float64, -0.0 as 0.0, one NaN."""
    values = np.asarray(values)
    if values.dtype.kind != "f":
        return values
    out = np.array(values, dtype=np.float64, copy=True)
    with np.errstate(invalid="ignore"):
        np.add(out, 0.0, out=out)
    np.copyto(out, np.nan, where=np.isnan(out))
    return out


def _zarr_arrays(store: Path) -> dict[str, np.ndarray]:
    root = zarr.open_group(str(store), mode="r", use_consolidated=False)
    found: dict[str, np.ndarray] = {}

    def walk(group, prefix: str) -> None:
        for name, array in group.arrays():
            found[prefix + name] = np.asarray(array[...])
        for name, sub in group.groups():
            walk(sub, prefix + name + "/")

    walk(root, "")
    return found


def _same_run(left: Path, right: Path) -> None:
    """Assert two run folders hold equal fields and equal numbers in their tables."""
    a, b = _zarr_arrays(left / "fields.zarr"), _zarr_arrays(right / "fields.zarr")
    assert set(a) == set(b), "the runs write different field arrays"
    for name in a:
        assert np.array_equal(_canonical(a[name]), _canonical(b[name]), equal_nan=True), (
            f"field {name!r} differs between the runs"
        )
    tables_a = {p.name for p in (left / "tables.parquet").glob("*.parquet")}
    tables_b = {p.name for p in (right / "tables.parquet").glob("*.parquet")}
    assert tables_a == tables_b, "the runs write different tables"
    for name in sorted(tables_a):
        frame_a = pd.read_parquet(left / "tables.parquet" / name)
        frame_b = pd.read_parquet(right / "tables.parquet" / name)
        numbers = [
            column
            for column in frame_a.columns
            if column not in IDENTITY_COLUMNS and frame_a[column].dtype.kind in "fiub"
        ]
        assert list(frame_a.columns) == list(frame_b.columns), f"table {name} changes its columns"
        for column in numbers:
            assert np.array_equal(
                _canonical(frame_a[column].to_numpy()),
                _canonical(frame_b[column].to_numpy()),
                equal_nan=True,
            ), f"column {column!r} of table {name} differs between the runs"


def _calibrate(variant: str, root: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Calibrate the variant under ``root`` in this process and return its session folder."""
    write_project(root / "project", island_files(variant))
    cache = root / "cache"
    link_binaries(cache, NEEDS)
    env = isolated_env(root / "home", cache, root / "state", root / "tmp")
    for key in ("HOME", "HMP_CACHE_HOME", "HMP_STATE_HOME", "HMP_NO_PROGRESS", "TZ"):
        monkeypatch.setenv(key, env[key])
    monkeypatch.setenv("HMP_DETERMINISTIC_FETCHED_AT", env["HMP_DETERMINISTIC_FETCHED_AT"])
    monkeypatch.chdir(root / "project")
    hmp.calibrate(root / "project" / "calib.toml")
    return root / "project" / "sessions" / variant


def _reuse_by_trial(session: Path) -> dict[int, list[str]]:
    reuse: dict[int, list[str]] = {}
    for line in (session / "trials.jsonl").read_text(encoding="utf-8").splitlines():
        row: dict[str, Any] = json.loads(line)
        if row["event"] == "finished":
            reuse[row["trial"]] = [p["reused"] for p in row["profile"] if p["kind"] == "solve"]
    return reuse


@pytest.mark.parametrize("variant", ["calage", "calage_sy"])
def test_trials_by_rerun_match_trials_by_build(
    variant: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rerun = _calibrate(variant, tmp_path / "rerun", monkeypatch)
    reuse = _reuse_by_trial(rerun)
    assert reuse == {1: ["no"], 2: ["rerun"], 3: ["rerun"]}, "the rerun session did not rerun"

    with monkeypatch.context() as patch:
        patch.setattr(Modflow6FlowAdapter, "rerun", lambda self, previous, model, slot: None)
        build = _calibrate(variant, tmp_path / "build", monkeypatch)
    assert _reuse_by_trial(build) == {1: ["no"], 2: ["no"], 3: ["no"]}, "the build session reran"

    trials_rerun, trials_build = read_trials(rerun), read_trials(build)
    assert len(trials_rerun) == len(trials_build) == 3
    for left, right in zip(trials_rerun, trials_build, strict=True):
        assert left.trial == right.trial
        assert left.cost == right.cost, f"trial {left.trial} costs another number"
        assert {
            k: v.model_dump(include={"cost", "components", "status"}) for k, v in left.cases.items()
        } == {
            k: v.model_dump(include={"cost", "components", "status"})
            for k, v in right.cases.items()
        }
        assert {k: p.value for k, p in left.params.items()} == {
            k: p.value for k, p in right.params.items()
        }

    series_rerun = read_trial_series(rerun)
    series_build = read_trial_series(build)
    assert len(series_rerun) > 0
    pd.testing.assert_frame_equal(series_rerun, series_build, check_exact=True)

    best_rerun = hmp.open(rerun)
    best_build = hmp.open(build)
    assert best_rerun.best_cost == best_build.best_cost
    assert best_rerun.best_parameters == best_build.best_parameters

    _same_run(
        tmp_path / "rerun" / "project" / "runs" / variant,
        tmp_path / "build" / "project" / "runs" / variant,
    )

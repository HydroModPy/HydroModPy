"""A set of runs names its metrics by metric, at the gauge, in the window of each run's rule.

``RunSet.metrics`` used to pivot every stored metric under ``<metric>_<station>``
(``nse_NANCON``), and ranking guessed the station when one was not given.
Here each run says, in its seal, where its headline NSE was read and on which
window; the columns are ``nse``, ``kge`` ... and the window travels with them.
Runs scored under different rules are not ranked together unless asked.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from hydromodpy.results.catalog.constants import UnrankedMetricError
from hydromodpy.results.catalog.facade import Catalog
from hydromodpy.results.metric_rule import DateWindow
from hydromodpy.results.run.group import RunSet
from hydromodpy.results.run.sealed import MixedWindowsError
from tests._helpers.metric_rows import GAUGE, headline_row, headline_score
from tests._helpers.run_records import (
    ATTEMPT_ID,
    SIM_ID,
    WINDOW,
    make_identity,
    make_record,
)


class _Directories:
    """A catalog handle that only knows where each run lives."""

    closed = False

    def __init__(self) -> None:
        self.dirs: dict[str, Path] = {}

    def run_dir_for(self, sim_id: str) -> Path:
        return self.dirs[sim_id]


@pytest.fixture(autouse=True)
def _no_index(monkeypatch):
    def _refuse(*_args, **_kwargs):
        raise AssertionError("reading the metrics of a set opened the index")

    monkeypatch.setattr(Catalog, "__init__", _refuse)


def _metrics(values: dict[str, float], window: DateWindow, station: str = GAUGE) -> dict:
    rows = [
        headline_row(
            name, value, station=station, window=window, n_samples=100, metric_rule_version="1"
        )
        for name, value in values.items()
    ]
    # A second station the run also observes: never mixed into the gauge columns.
    rows.append(rows[0].model_copy(update={"station": "OTHER", "value": -5.0}))
    score = headline_score(
        values.get("nse"), station=station, window=window, n_samples=100, metric_rule_version="1"
    )
    return {"metrics": rows, "score": score}


def _seal(catalog: _Directories, root: Path, name: str, index: int, metrics: dict) -> str:
    sim_id = SIM_ID[:-2] + f"{index:02d}"
    record = make_record(**metrics)
    run = record.run.model_copy(update={"sim_id": sim_id, "name": name, "rel_dir": f"runs/{name}"})
    record = record.model_copy(
        update={
            "run": run,
            "identity": make_identity(sim_id=sim_id, attempt_id=ATTEMPT_ID),
            "provenance": record.provenance.model_copy(update={"sim_id": sim_id}),
        }
    )
    run_dir = root / "runs" / name
    run_dir.mkdir(parents=True)
    record.write(run_dir)
    catalog.dirs[sim_id] = run_dir
    return sim_id


@pytest.fixture
def scored(tmp_path):
    """Three sealed runs on one window, and a run that never completed."""
    catalog = _Directories()
    ids = {
        "a": _seal(
            catalog, tmp_path, "a", 1, _metrics({"nse": 0.6, "rmse": 2.0, "pbias": -20.0}, WINDOW)
        ),
        "b": _seal(
            catalog, tmp_path, "b", 2, _metrics({"nse": 0.9, "rmse": 0.5, "pbias": 5.0}, WINDOW)
        ),
        "c": _seal(
            catalog, tmp_path, "c", 3, _metrics({"nse": 0.3, "rmse": 3.0, "pbias": 30.0}, WINDOW)
        ),
    }
    failed = tmp_path / "runs" / "d"
    failed.mkdir(parents=True)
    ids["d"] = SIM_ID[:-2] + "04"
    catalog.dirs[ids["d"]] = failed
    return catalog, ids


def test_the_metric_columns_are_named_by_metric_and_carry_the_window(scored) -> None:
    catalog, ids = scored
    frame = RunSet(list(ids.values()), catalog).metrics

    assert list(frame.columns[:7]) == [
        "sim_id",
        "station",
        "variable",
        "window_start",
        "window_end",
        "n_samples",
        "metric_rule_version",
    ]
    assert {"nse", "rmse", "pbias"} <= set(frame.columns)
    assert not any("_" + GAUGE in column for column in frame.columns)
    by_id = frame.set_index("sim_id")
    assert by_id.loc[ids["b"], "nse"] == pytest.approx(0.9)
    assert by_id.loc[ids["b"], "station"] == GAUGE
    assert by_id.loc[ids["b"], "window_start"] == WINDOW.start
    # A run that never completed is listed with empty cells.
    assert by_id.loc[ids["d"]].isna().all()


@pytest.mark.parametrize(
    ("metric", "best", "worst"),
    [("nse", "b", "c"), ("rmse", "b", "c"), ("pbias", "b", "c")],
)
def test_best_and_worst_follow_the_metric(scored, metric, best, worst) -> None:
    catalog, ids = scored
    group = RunSet(list(ids.values()), catalog)

    assert group.best(metric).sim_id == ids[best]
    assert group.worst(metric).sim_id == ids[worst]


def test_compare_lists_best_first_with_the_window(scored) -> None:
    catalog, ids = scored
    table = RunSet(list(ids.values()), catalog).compare("rmse")

    assert list(table["sim_id"]) == [ids["b"], ids["a"], ids["c"]]
    assert list(table["name"]) == ["b", "a", "c"]
    assert set(table["station"]) == {GAUGE}
    assert set(table["window_end"]) == {WINDOW.end}


def test_sort_by_orders_the_raw_value(scored) -> None:
    catalog, ids = scored
    group = RunSet(list(ids.values()), catalog)

    assert group.sort_by("nse").sim_ids == [ids["c"], ids["a"], ids["b"]]
    assert group.sort_by("nse", ascending=False).sim_ids == [ids["b"], ids["a"], ids["c"]]


def test_runs_scored_on_different_windows_are_not_ranked_together(scored, tmp_path) -> None:
    catalog, ids = scored
    other = DateWindow(start=date(2010, 1, 1), end=date(2012, 12, 31))
    late = _seal(catalog, tmp_path, "e", 5, _metrics({"nse": 0.99}, other))
    group = RunSet([*ids.values(), late], catalog)

    with pytest.raises(MixedWindowsError, match="discharge at J0014010, 2010-01-01 to 2012-12-31"):
        group.best("nse")
    assert group.best("nse", mixed_windows=True).sim_id == late


def test_runs_scored_at_different_stations_are_not_ranked_together(scored, tmp_path) -> None:
    catalog, ids = scored
    elsewhere = _seal(
        catalog, tmp_path, "f", 6, _metrics({"nse": 0.99}, WINDOW, station="J9999999")
    )
    group = RunSet([*ids.values(), elsewhere], catalog)

    with pytest.raises(MixedWindowsError, match="discharge at J9999999"):
        group.best("nse")
    with pytest.raises(MixedWindowsError, match="different rules"):
        group.compare("nse")
    assert group.best("nse", mixed_windows=True).sim_id == elsewhere


def test_an_unranked_metric_and_an_absent_one_are_refused(scored) -> None:
    catalog, ids = scored
    group = RunSet(list(ids.values()), catalog)

    with pytest.raises(UnrankedMetricError, match="no declared direction"):
        group.best("bias_of_the_day")
    with pytest.raises(UnrankedMetricError, match="write 'nse_log'"):
        group.best("log_nse")
    with pytest.raises(KeyError, match="kge"):
        group.best("kge")
    with pytest.raises(ValueError, match="Empty group"):
        RunSet([], catalog).best("nse")

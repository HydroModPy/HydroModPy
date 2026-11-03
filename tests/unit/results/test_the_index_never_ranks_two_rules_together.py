"""The index ranks scores only under one rule, as ``RunSet.best`` does.

A 90-day NSE of 0.97 ranked above a 5-year NSE of 0.60 in ``Catalog.best``,
``@best:nse`` and ``find(nse_gt=...)``: each ordered the ``metrics`` rows
whatever their window, station or variable. They now refuse, naming the rules
found, unless ``mixed_windows=True``. ``hmp catalog rank`` and the best-per-project
view have their own files.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from hydromodpy.project.accessors import ProjectRunsAccessor
from hydromodpy.results.catalog import Catalog, rebuild_index
from hydromodpy.results.metric_rule import DateWindow
from hydromodpy.results.run.sealed import MixedWindowsError
from tests._helpers.sealed_runs import make_project, seal_run

pytestmark = pytest.mark.unit

FIVE_YEARS = DateWindow(start=date(2016, 1, 1), end=date(2020, 12, 31))
NINETY_DAYS = DateWindow(start=date(2020, 10, 1), end=date(2020, 12, 29))


@pytest.fixture
def windows(tmp_path):
    """One site, one gauge, two windows: a short good score and a long poor one."""
    root = make_project(tmp_path / "demo")
    ids = {
        "short": seal_run(root, "short", nse=0.97, window=NINETY_DAYS),
        "long": seal_run(root, "long", nse=0.60, window=FIVE_YEARS),
        "long2": seal_run(root, "long2", nse=0.55, window=FIVE_YEARS),
    }
    rebuild_index(root)
    with Catalog(root) as cat:
        yield cat, ids


@pytest.fixture
def stations(tmp_path):
    """Two sites, so two gauges, on the same window."""
    root = make_project(tmp_path / "demo")
    ids = {
        "a1": seal_run(root, "a1", site="J001", nse=0.8, window=FIVE_YEARS),
        "a2": seal_run(root, "a2", site="J001", nse=0.7, window=FIVE_YEARS),
        "b1": seal_run(root, "b1", site="J002", nse=0.9, window=FIVE_YEARS),
    }
    rebuild_index(root)
    with Catalog(root) as cat:
        yield cat, ids


@pytest.mark.parametrize("call", ["best", "worst", "rank"])
def test_the_methods_refuse_two_windows(windows, call) -> None:
    cat, _ids = windows
    with pytest.raises(MixedWindowsError, match="--mixed-windows") as refused:
        getattr(cat, call)("demo", "nse")
    assert "2016-01-01 to 2020-12-31" in str(refused.value)
    assert "2020-10-01 to 2020-12-29" in str(refused.value)


def test_mixed_windows_forces_the_ranking(windows) -> None:
    cat, ids = windows
    assert cat.best("demo", "nse", mixed_windows=True).sim_id == ids["short"]
    assert cat.worst("demo", "nse", mixed_windows=True).sim_id == ids["long2"]
    ranked = cat.rank("demo", "nse", n=3, mixed_windows=True)
    assert ranked.sim_ids == [ids["short"], ids["long"], ids["long2"]]


def test_a_selector_refuses_two_windows(windows) -> None:
    cat, ids = windows
    with pytest.raises(MixedWindowsError, match="name the run by its directory"):
        cat.resolve("@best:nse")
    with pytest.raises(MixedWindowsError):
        cat.resolve("@worst:nse")
    assert cat.resolve("@best:nse", mixed_windows=True) == ids["short"]


def test_two_stations_are_refused_and_a_named_station_is_not(stations) -> None:
    cat, ids = stations
    with pytest.raises(MixedWindowsError, match="J001") as refused:
        cat.best("demo", "nse")
    assert "J002" in str(refused.value)
    with pytest.raises(MixedWindowsError):
        cat.resolve("@best:nse")
    assert cat.resolve("@best:nse@J001") == ids["a1"]
    assert cat.resolve("@worst:nse@J001") == ids["a2"]
    assert cat.resolve("@best:nse", mixed_windows=True) == ids["b1"]


def test_a_named_station_still_needs_one_window(windows) -> None:
    cat, ids = windows
    with pytest.raises(MixedWindowsError):
        cat.resolve("@best:nse@J0014010")
    assert cat.resolve("@best:nse@J0014010", mixed_windows=True) == ids["short"]


def test_a_filter_on_a_metric_refuses_two_windows(windows) -> None:
    cat, ids = windows
    with pytest.raises(MixedWindowsError, match="--mixed-windows"):
        cat.find(nse_gt=0.5)
    # A filter that names no metric ranks nothing.
    assert len(cat.find(status="completed")) == 3
    assert set(cat.find(nse_gt=0.5, mixed_windows=True).sim_ids) == set(ids.values())


def test_a_filter_on_a_metric_under_one_rule_answers(stations) -> None:
    cat, ids = stations
    assert set(cat.find(site="J001", nse_gt=0.75).sim_ids) == {ids["a1"]}


def test_the_project_accessor_refuses_two_windows(windows) -> None:
    cat, ids = windows
    runs = ProjectRunsAccessor(SimpleNamespace(_store=cat, _project_name="demo"))
    with pytest.raises(MixedWindowsError, match="--mixed-windows"):
        runs.best("nse")
    assert runs.best("nse", mixed_windows=True).sim_id == ids["short"]

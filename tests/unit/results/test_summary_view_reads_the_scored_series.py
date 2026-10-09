"""The summary view carries the metrics a run recorded, wherever it scored them.

A run scored against a gauge on discharge stores its metrics under that gauge.
The view used to read the outlet station on variable ``head`` only, so its
``nse`` was NULL for every such run, here and in the federated view.
"""

from __future__ import annotations

import uuid

import pytest

from hydromodpy.results.catalog.constants import OUTLET_STATION
from tests._helpers.fixtures_catalog import simulation_catalog


@pytest.fixture
def catalog(tmp_path):
    with simulation_catalog(tmp_path / "ws") as cat:
        yield cat


def _run(cat, name: str, rows: list[tuple[str, str, str, float]]) -> str:
    sid = str(uuid.uuid4())
    cat.register_simulation(sid, project="p", solver="modflow6", name=name)
    for station, variable, metric, value in rows:
        cat.write_metric(sid, station, metric, value, variable=variable)
    cat.finalize(sid, "completed")
    return sid


def _summary(cat, sid: str) -> dict[str, float | None]:
    row = cat.backend.fetch_one(
        "SELECT nse, kge, rmse FROM v_simulation_summary WHERE sim_id = ?", [sid]
    )
    return dict(zip(("nse", "kge", "rmse"), row, strict=True))


def test_a_run_scored_on_one_gauge_shows_its_scores(catalog) -> None:
    sid = _run(
        catalog,
        "gauged",
        [("GAUGE", "discharge", "nse", 0.7), ("GAUGE", "discharge", "rmse", 0.02)],
    )
    assert _summary(catalog, sid) == {"nse": 0.7, "kge": None, "rmse": 0.02}


def test_the_outlet_wins_over_another_station(catalog) -> None:
    sid = _run(
        catalog,
        "both",
        [(OUTLET_STATION, "head", "nse", 0.9), ("GAUGE", "discharge", "nse", 0.4)],
    )
    assert _summary(catalog, sid)["nse"] == 0.9


def test_two_gauges_and_no_outlet_give_no_single_value(catalog) -> None:
    sid = _run(
        catalog,
        "two",
        [("A", "discharge", "nse", 0.6), ("B", "discharge", "nse", 0.3)],
    )
    assert _summary(catalog, sid)["nse"] is None

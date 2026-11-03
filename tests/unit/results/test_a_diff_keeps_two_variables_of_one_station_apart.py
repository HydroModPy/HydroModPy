"""``Catalog.diff`` and ``compare_pair`` key a score on (metric, station, variable).

They pivoted on (metric, station), so the discharge and the level of one station
merged into one row, and nothing said on which window or how many samples each
side was scored.
"""

from __future__ import annotations

from datetime import date

import pytest

from hydromodpy.analysis.comparison.pairwise import compare_pair
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.manifest import MetricRow
from hydromodpy.results.metric_rule import DateWindow
from hydromodpy.results.storage.sealing import seal_completed
from tests._helpers.metric_rows import headline_row
from tests._helpers.run_stores import open_run_store

STATION = "J0014010"


def _row(variable: str, value: float, start: date, n: int) -> MetricRow:
    window = DateWindow(start=start, end=date(2020, 12, 31))
    return headline_row(
        "nse", value, station=STATION, variable=variable, window=window, n_samples=n
    )


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "p"
    scores = {
        "a": [
            _row("discharge", 0.6, date(2016, 1, 1), 1827),
            _row("level", 0.2, date(2016, 1, 1), 1827),
        ],
        "b": [
            _row("discharge", 0.7, date(2018, 1, 1), 1096),
            _row("level", 0.9, date(2016, 1, 1), 1827),
        ],
    }
    for name, rows in scores.items():
        store = open_run_store(root, name, create_zarr=False)
        for row in rows:
            store.facts.put_metric(row)
        seal_completed(store)
    rebuild_index(root)
    return root


def test_the_diff_keeps_each_variable_of_a_station(project) -> None:
    with Catalog(project) as cat:
        delta = cat.diff("a", "b")["metrics"]
    assert {key[:3] for key in delta} == {
        ("nse", STATION, "discharge"),
        ("nse", STATION, "level"),
    }


def test_the_diff_shows_the_window_and_the_samples_of_each_side(project) -> None:
    with Catalog(project) as cat:
        delta = cat.diff("a", "b")["metrics"]
    side_a, side_b = delta[("nse", STATION, "discharge")]
    assert (side_a["value"], side_a["n"], side_a["window_start"]) == (0.6, 1827, date(2016, 1, 1))
    assert (side_b["value"], side_b["n"], side_b["window_start"]) == (0.7, 1096, date(2018, 1, 1))


def test_compare_pair_has_one_row_per_variable_with_its_window(project) -> None:
    frame = compare_pair("a", "b", workspace=project).reset_index()
    assert sorted(frame["variable"]) == ["discharge", "level"]
    discharge = frame[frame["variable"] == "discharge"].iloc[0]
    assert (discharge["A"], discharge["B"]) == (0.6, 0.7)
    assert (discharge["A_n"], discharge["B_n"]) == (1827, 1096)
    assert discharge["A_window"] == "2016-01-01/2020-12-31"
    assert discharge["B_window"] == "2018-01-01/2020-12-31"


def _run_diff(project, capsys, fmt: str) -> str:
    import argparse

    from hydromodpy.cli.commands.catalog import diff

    args = argparse.Namespace(
        ref_a="a", ref_b="b", workspace=str(project), format=fmt, verbose=0, quiet=False
    )
    diff.run(args)
    return capsys.readouterr().out


def test_the_cli_prints_each_variable_with_its_window(project, capsys) -> None:
    text = _run_diff(project, capsys, "table")
    assert f"nse@{STATION}/discharge: 0.6 [2016-01-01/2020-12-31, n=1827]" in text
    assert "0.7 [2018-01-01/2020-12-31, n=1096]" in text
    assert f"nse@{STATION}/level" in text


def test_the_cli_json_rows_carry_station_variable_and_windows(project, capsys) -> None:
    import json

    rows = json.loads(_run_diff(project, capsys, "json"))["data"]["metrics"]
    discharge = next(row for row in rows if row["variable"] == "discharge")
    assert discharge["station"] == STATION
    assert discharge["a"]["n"] == 1827
    assert discharge["b"]["window"] == "2018-01-01/2020-12-31"

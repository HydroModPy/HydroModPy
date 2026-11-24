"""The network criterion scored again on a stored run, on runs whose answer is known.

The steady run is the 5 x 3 valley of ``tests.unit.display._network_comparison_run``,
whose mapped network is the axis column. The transient run is the monthly valley of
``tests._helpers.transient_network_run``: the whole axis flows five months of twelve,
the outlet every month, over 2001 and 2002 whole and 2003 up to March. The maximal
map is the whole axis, the minimal map its two southern cells.
"""

from __future__ import annotations

import math
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hydromodpy.catchment.stream_network.extent import calendar_years, yearly_flow_counts
from hydromodpy.core.scoring.stream_defaults import parse_visible_flow
from hydromodpy.results.derive.stream_network import run_score
from hydromodpy.results.derive.stream_network.criterion_score import score_extent
from hydromodpy.results.derive.stream_network.run_extent import run_step_edges
from hydromodpy.results.derive.stream_network.run_score import (
    NETWORK_SCORE_COLUMNS,
    _bound_of,
    _run_maps,
    network_score_table,
)
from hydromodpy.results.storage.contract import RUN_RESOLVED_CONFIG_FILENAME
from tests._helpers.transient_network_run import transient_run
from tests.unit.display._network_comparison_run import AXIS_COLUMN, cell, comparison_run

TWO_MAPS_OUTPUT = """
[searched_under.outputs.net]
support = "network"
map = { complete = "data.hydrography", permanent = "data.hydrography", drawn_by = "crossing", calibrate_on = { permanent = 0.25, complete = 0.75 } }
model = { seepage_threshold = 0.0, extent = { flowing_at_least = "1 month", dry_at_most = "1 month", year_quorum = 1.0, visible_flow = "0 L/s" } }

[searched_under.window]
start = "2002-01-01"
"""


def value(table: pd.DataFrame, quantity: str, bound: str | None = None, year=None) -> float:
    rows = table[table["quantity"] == quantity]
    rows = rows[rows["bound"].isna()] if bound is None else rows[rows["bound"] == bound]
    rows = rows[rows["year"].isna()] if year is None else rows[rows["year"] == year]
    assert len(rows) == 1, rows
    return float(rows["value"].iloc[0])


def sealed(run, folder: Path, text: str):
    (folder / RUN_RESOLVED_CONFIG_FILENAME).write_text(text, encoding="utf-8")
    run.dir = folder
    return run


@pytest.mark.parametrize(
    ("key", "split"),
    [
        ("J_signed", ("J_signed", None, None)),
        ("J_signed_maximal", ("J_signed", "maximal", None)),
        ("J_signed_minimal_y2001", ("J_signed", "minimal", 2001)),
        ("D_so_maximal_validation", ("D_so", "maximal_validation", None)),
        ("year_scored_y2003", ("year_scored", None, 2003)),
        ("frac_minimal_outside_maximal", ("frac_minimal_outside_maximal", None, None)),
        ("minimal_dry_steps", ("minimal_dry_steps", None, None)),
        ("weight_minimal", ("weight", "minimal", None)),
    ],
)
def test_a_component_splits_into_quantity_bound_and_year(key, split) -> None:
    assert _bound_of(key) == split


def test_a_steady_run_is_scored_in_one_state_on_the_axis(tmp_path) -> None:
    # The axis head seeps, so the simulated network is the axis: the mapped one.
    run = comparison_run(seepage_cells=[cell(AXIS_COLUMN, 2)])
    run.dir = tmp_path

    table = network_score_table(run)

    assert tuple(table.columns) == NETWORK_SCORE_COLUMNS
    assert set(table["mode"]) == {"one_state"}
    assert table["output"].isna().all()
    assert value(table, "J_signed", "maximal") == 0.0
    assert value(table, "D_so", "maximal") == 0.0
    assert value(table, "n_network_sim", "maximal") == 3.0
    assert value(table, "n_bounds_scored") == 1.0
    # One bound publishes its distances once, under its bound.
    assert not ((table["quantity"] == "J_signed") & table["bound"].isna()).any()


def test_a_transient_run_without_an_output_is_scored_on_two_bounds_with_the_defaults(
    tmp_path,
) -> None:
    run = transient_run()
    run.dir = tmp_path

    table = network_score_table(run)

    assert set(table["mode"]) == {"two_bounds"}
    assert set(table["window_name"]) == {"all"}
    # The defaults declare no permanent map: the maximal bound alone.
    assert value(table, "n_bounds_scored") == 1.0
    assert value(table, "n_years_scored") == 2.0
    assert value(table, "year_scored", year=2003) == 0.0
    assert value(table, "J_signed", "maximal") == 0.0
    assert value(table, "J_signed", "maximal", year=2001) == 0.0


def test_two_maps_score_as_a_trial_counts_the_stack_in_memory(tmp_path) -> None:
    run = sealed(transient_run(), tmp_path, TWO_MAPS_OUTPUT)

    table = network_score_table(run)

    # The sealed window leaves 2001 out.
    assert set(table["window_name"]) == {"calibration"}
    assert value(table, "n_years_scored") == 1.0
    assert value(table, "year_scored", year=2001) == 0.0
    assert value(table, "weight", "minimal") == 0.25
    assert value(table, "weight", "maximal") == 0.75
    assert value(table, "frac_minimal_outside_maximal") == 0.0
    # The maximal extent is the axis, the map. The minimal extent is the outlet
    # alone, and the minimal map holds the middle axis cell too: a deficit.
    assert value(table, "J_signed", "maximal") == 0.0
    assert value(table, "J_signed", "minimal") < 0.0

    # The same numbers from the stack held whole, as a trial counts it.
    from hydromodpy.results.derive.stream_network.criterion_settings import (
        network_criterion_settings,
    )

    settings = network_criterion_settings(run)
    maps = _run_maps(run, settings, project_root=None, geometries=None)
    years = calendar_years(run_step_edges(run), window=settings.window)
    counts = yearly_flow_counts(
        run.stack,
        years=years,
        threshold_m3_s=maps.maximal.geometry.threshold_m3_s,
        metric=maps.maximal.geometry.metric,
        visible_flow=parse_visible_flow("0 L/s"),
        outlet=maps.maximal.geometry.outlet,
    )
    _, expected = score_extent(
        "net",
        counts,
        years,
        maps.maximal,
        maps.minimal,
        maximal_flowing_steps=1,
        minimal_dry_steps=1,
        year_quorum=1.0,
        weights=(0.25, 0.75),
        weighting="cell",
        validity_length_m=None,
        step_days=30.4375,
        visible=parse_visible_flow("0 L/s"),
    )
    for key, number in expected.items():
        quantity, bound, year = _bound_of(key)
        if bound is None and year is None and key not in ("n_years_scored",):
            continue
        got = value(table, quantity, bound, year)
        assert got == number or (math.isnan(got) and math.isnan(number)), key


def test_named_windows_give_one_block_each(tmp_path) -> None:
    run = transient_run()
    run.dir = tmp_path

    table = network_score_table(
        run, window={"first": ("2001-01-01", "2001-12-31"), "both": (None, None)}
    )

    assert value(table[table["window_name"] == "first"], "n_years_scored") == 1.0
    assert value(table[table["window_name"] == "both"], "n_years_scored") == 2.0
    first = table[table["window_name"] == "first"]
    assert first["window_start"].iloc[0] == date(2001, 1, 1)
    assert first["window_end"].iloc[0] == date(2001, 12, 31)


def test_runs_that_share_their_maps_build_them_once(tmp_path, monkeypatch) -> None:
    built: list[int] = []
    real = run_score.criterion_geometry

    def counted(*args, **kwargs):
        built.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(run_score, "criterion_geometry", counted)
    geometries: dict = {}
    first, second = transient_run(), transient_run(summer_release=0.0)
    first.dir, second.dir = tmp_path, tmp_path

    one = network_score_table(first, geometries=geometries)
    two = network_score_table(second, geometries=geometries)

    assert len(built) == 1
    assert value(one, "n_network_sim", "maximal") == value(two, "n_network_sim", "maximal")


def test_a_file_map_is_cut_to_the_stored_watershed(tmp_path) -> None:
    import geopandas as gpd
    from shapely.geometry import LineString

    from tests.unit.display._network_comparison_run import CELL_M, CRS, NY

    x = (AXIS_COLUMN + 0.5) * CELL_M
    path = tmp_path / "map.gpkg"
    # The line runs on 300 m past the northern edge, out of the watershed.
    gpd.GeoDataFrame(
        geometry=[LineString([(x, 0.1 * CELL_M), (x, (NY + 3) * CELL_M)])], crs=CRS
    ).to_file(path)
    run = sealed(
        comparison_run(seepage_cells=[cell(AXIS_COLUMN, 2)]),
        tmp_path,
        '[searched_under.outputs.net]\nsupport = "network"\n'
        'map = { complete = "map.gpkg", drawn_by = "crossing" }\n',
    )

    table = network_score_table(run, project_root=tmp_path)

    assert value(table, "observed_network_clipped", "maximal") == 1.0
    assert value(table, "n_observed_cells", "maximal") == 3.0
    assert value(table, "J_signed", "maximal") == 0.0
    assert np.isfinite(value(table, "cell_spacing_m"))


def test_the_window_columns_join_the_rows_of_the_series_score(tmp_path) -> None:
    # Run.score closes an open bound on the series: the start of the first
    # period and the last stamp. The network rows close it the same way.
    from hydromodpy.results.score_table import resolve_windows

    run = transient_run()
    run.dir = tmp_path
    windows = {"late": ("2002-01-01", None), "all": (None, None)}
    series = pd.DataFrame(
        {"time": pd.to_datetime(run.index).tz_localize("UTC"), "source": "simulated"}
    )

    table = network_score_table(run, window=windows)
    resolved = resolve_windows(windows, series, period_start="2001-01-01")

    series_rows = pd.DataFrame(
        [(name, w.start, w.end) for name, w in resolved],
        columns=["window_name", "window_start", "window_end"],
    )
    joined = table.merge(series_rows, on=["window_name", "window_start", "window_end"])
    assert len(joined) == len(table)

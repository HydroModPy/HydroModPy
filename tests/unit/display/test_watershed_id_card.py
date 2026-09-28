"""The identity card prints facts a first-time reader can use, and all of them.

Measured on the example 04 gallery: the card read ``Status: running`` on every
finished run, because it is drawn before the run is sealed; it printed a raw
id prefix nobody can decode; and the project and run names, forty and thirty
characters long, ran off the edge of the page.
"""

from __future__ import annotations

from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

from hydromodpy.display.figures.watershed_id_card import (
    VALUE_LINES,
    VALUE_WIDTH,
    WatershedIdCardFigure,
    identity_rows,
    wrap_value,
)

PROJECT = "04_streamflow_intermittence_in_transient"
NAME = "nancon_intermittence_mf6_daily"


@pytest.fixture
def mpl():
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    yield plt
    plt.close("all")


def _run(*, edges=None) -> SimpleNamespace:
    watershed = gpd.GeoDataFrame(geometry=[box(0.0, 0.0, 8_000.0, 8_000.0)], crs="EPSG:2154")
    dem = np.linspace(100.0, 200.0, 16, dtype=float).reshape(4, 4)
    raster = SimpleNamespace(
        data=dem, transform=(2_000.0, 0.0, 0.0, 0.0, -2_000.0, 8_000.0), nodata=None
    )
    return SimpleNamespace(
        sim_id="c11914ab-5f1e-4a55-9f1c-2e6d9b0a7d11",
        name=NAME,
        project=PROJECT,
        solver="modflow6",
        flow_regime="transient",
        status="running",
        n_cells=21_406,
        n_layers=1,
        n_timesteps=1_096 if edges is None else len(edges) - 1,
        periods=SimpleNamespace(
            edges=pd.date_range("2000-01-01", "2003-01-01", freq="D") if edges is None else edges
        ),
        geographic=lambda feature: watershed,
        geographic_raster=lambda name: raster,
        has_field=lambda *_, **__: False,
        has_table=lambda *_, **__: False,
    )


def test_the_card_prints_no_status_and_no_raw_id() -> None:
    rows = dict(identity_rows(_run()))

    assert "Status" not in rows
    assert "ID" not in rows
    assert "running" not in rows.values()
    assert not any("c11914ab" in value for value in rows.values())


def test_the_card_names_the_solver_the_period_the_steps_and_the_area() -> None:
    rows = dict(identity_rows(_run()))

    assert rows["Solver"] == "MODFLOW 6"
    assert rows["Period"] == "2000-01-01 to 2002-12-31"
    assert rows["Time steps"] == "1,096 daily"
    assert rows["Catchment area"] == "64.0 km²"


def test_a_monthly_run_says_monthly() -> None:
    edges = pd.date_range("2000-01-01", "2003-01-01", freq="MS")

    assert dict(identity_rows(_run(edges=edges)))["Time steps"] == "36 monthly"


def test_a_row_the_run_does_not_hold_is_left_out() -> None:
    run = _run()
    run.periods = SimpleNamespace(edges=None)
    run.geographic = lambda feature: (_ for _ in ()).throw(KeyError(feature))

    rows = dict(identity_rows(run))

    assert "Period" not in rows
    assert "Catchment area" not in rows
    assert rows["Time steps"] == "1,096"


def test_a_long_snake_case_name_wraps_on_its_underscores() -> None:
    wrapped = wrap_value(PROJECT)

    lines = wrapped.split("\n")
    assert len(lines) <= VALUE_LINES
    assert all(len(line) <= VALUE_WIDTH for line in lines)
    assert "".join(lines) == PROJECT


def test_a_value_too_long_for_two_lines_ends_with_an_ellipsis() -> None:
    wrapped = wrap_value("_".join([PROJECT] * 3))

    lines = wrapped.split("\n")
    assert len(lines) == VALUE_LINES
    assert lines[-1].endswith("…")


def test_no_value_runs_past_its_cell_or_the_page(mpl) -> None:
    fig = WatershedIdCardFigure().plot(_run(), dpi=80)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    page = fig.bbox

    table = next(ax for ax in fig.axes if ax.tables).tables[0]
    for cell in table.get_celld().values():
        text = cell.get_text().get_window_extent(renderer)
        frame = cell.get_window_extent(renderer)
        assert text.x1 <= frame.x1 + 1.0, cell.get_text().get_text()
        assert text.x1 <= page.x1

"""Cohort figures: one row per site of ``summary/by_site``, never a run.

K is in m/s, nse is dimensionless, outlets are in metres of one CRS. A missing
value (one site without K) is drawn hollow or counted, and never dropped silently.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.display import cohort, static
from hydromodpy.display.cohort import draw_distribution, draw_map, wants_log
from hydromodpy.display.theme import THEMES

THEME = THEMES["default"]


def drawn(draw, table, variable):
    fig = static.new_figure(THEME)
    draw(table, variable, fig.axes[0], THEME)
    return fig, fig.axes[0]


def site_table(**extra) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "site": ["J0014010", "J0170000", "J0200000"],
            "K": [2e-5, 3e-7, None],
            "nse": [0.8, 0.5, 0.3],
            "x_outlet": [350000.0, 360000.0, 370000.0],
            "y_outlet": [6800000.0, 6810000.0, 6820000.0],
            "crs": ["EPSG:2154"] * 3,
        }
    )
    return frame.assign(**extra)


@pytest.mark.parametrize("draw", [draw_map, draw_distribution])
def test_refuses_a_run(draw):
    with pytest.raises(ValueError, match="cohort table"):
        drawn(draw, object(), "nse")


def test_map_outlets(mpl):
    _, ax = drawn(draw_map, site_table(), "K")
    assert "K of the best case of each site (3 sites)" in ax.get_title()
    assert ax.get_legend() is not None
    assert [text.get_text() for text in ax.texts] == ["J0014010", "J0170000", "J0200000"]
    assert ax.collections[0].norm.__class__.__name__ == "LogNorm"


def test_distribution_counts_missing(mpl):
    _, ax = drawn(draw_distribution, site_table(), "K")
    assert ax.get_title() == "K over 2 sites, 1 without a value"
    assert ax.get_xscale() == "log"


def test_a_summary_writes_a_png_and_skips_a_refused_figure(mpl, tmp_path):
    written, skipped = cohort.draw_cohort_figures(site_table(), ["map"], ["nse", "Sy"], tmp_path)

    assert [path.name for path in written] == ["map_nse.png"] and written[0].exists()
    assert "map of Sy: the cohort table has no column 'Sy'" in skipped[0]
    assert "display.figures.map" in (tmp_path / "index.json").read_text()


WANTS_LOG = [
    pytest.param(np.array([1e-6, 1e-4]), None, True, id="two decades"),
    pytest.param(np.array([1e-5, 2e-5]), None, False, id="less than a decade"),
    pytest.param(np.array([-1.0, 10.0]), None, False, id="negative value"),
    pytest.param(np.array([1.0, 2.0]), True, True, id="forced"),
]


@pytest.mark.parametrize(("values", "forced", "expected"), WANTS_LOG)
def test_wants_log(values, forced, expected):
    assert bool(wants_log(values, forced)) is expected


# Each row is the figure, the table, the variable and the start of the message.
REFUSALS = [
    pytest.param(
        "map",
        site_table(crs=["EPSG:2154", "EPSG:2154", "EPSG:4326"]),
        "nse",
        "2 CRS",
        id="outlets in two CRS",
    ),
    pytest.param("distribution", site_table(), "Sy", "no column 'Sy'.*site", id="unknown column"),
]


@pytest.mark.parametrize(("name", "table", "variable", "message"), REFUSALS)
def test_refusals(mpl, name, table, variable, message):
    with pytest.raises(ValueError, match=message):
        drawn(cohort.COHORT_FIGURES[name].draw, table, variable)

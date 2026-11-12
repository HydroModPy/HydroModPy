"""Cohort figures: one row per site of ``summary/by_site``, never a run.

K is in m/s, nse is dimensionless, outlets are in metres of one CRS. A missing
value (one site without K) is drawn hollow or counted, and never dropped silently.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.display import figure_registry
from hydromodpy.display.figures._cohort import wants_log


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


@pytest.mark.parametrize("name", ["map", "distribution"])
def test_refuses_a_run(name):
    figure = figure_registry.get(name)

    reason = figure.unavailable_reason(object())

    assert reason is not None and "cohort table" in reason
    assert figure.unavailable_reason(site_table()) is None


def test_map_outlets(mpl):
    fig = figure_registry.get("map").plot(site_table(), variable="K")
    ax = fig.axes[0]

    assert "K of the best case of each site (3 sites)" in ax.get_title()
    assert ax.get_legend() is not None
    assert [text.get_text() for text in ax.texts] == ["J0014010", "J0170000", "J0200000"]
    assert ax.collections[0].norm.__class__.__name__ == "LogNorm"


def test_distribution_counts_missing(mpl):
    fig = figure_registry.get("distribution").plot(site_table(), variable="K")
    ax = fig.axes[0]

    assert ax.get_title() == "K over 2 sites, 1 without a value"
    assert ax.get_xscale() == "log"


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
        figure_registry.get(name).plot(table, variable=variable)

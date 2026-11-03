"""The cohort figures draw ``summary/by_site``, one row per site, never a run."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.display import figure_registry
from hydromodpy.display.figures.cohort_table import wants_log


@pytest.fixture
def mpl():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    yield plt
    plt.close("all")


def _table(**extra) -> pd.DataFrame:
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
def test_a_cohort_figure_refuses_a_run(name: str) -> None:
    figure = figure_registry.get(name)

    reason = figure.unavailable_reason(object())

    assert reason is not None and "cohort table" in reason
    assert figure.unavailable_reason(_table()) is None


def test_the_map_colors_each_outlet_and_leaves_a_missing_value_hollow(mpl) -> None:
    fig = figure_registry.get("map").plot(_table(), variable="K")
    ax = fig.axes[0]

    assert "K of the best case of each site (3 sites)" in ax.get_title()
    assert ax.get_legend() is not None
    assert [text.get_text() for text in ax.texts] == ["J0014010", "J0170000", "J0200000"]
    assert ax.collections[0].norm.__class__.__name__ == "LogNorm"


def test_the_map_refuses_outlets_in_two_crs(mpl) -> None:
    table = _table(crs=["EPSG:2154", "EPSG:2154", "EPSG:4326"])

    with pytest.raises(ValueError, match="2 CRS"):
        figure_registry.get("map").plot(table, variable="nse")


def test_the_distribution_counts_the_sites_without_a_value(mpl) -> None:
    fig = figure_registry.get("distribution").plot(_table(), variable="K")
    ax = fig.axes[0]

    assert ax.get_title() == "K over 2 sites, 1 without a value"
    assert ax.get_xscale() == "log"


def test_an_unknown_column_names_the_columns_the_table_has(mpl) -> None:
    with pytest.raises(ValueError, match="no column 'Sy'.*site"):
        figure_registry.get("distribution").plot(_table(), variable="Sy")


def test_a_log_scale_needs_positive_values_over_a_decade() -> None:
    assert wants_log(np.array([1e-6, 1e-4]), None)
    assert not wants_log(np.array([1e-5, 2e-5]), None)
    assert not wants_log(np.array([-1.0, 10.0]), None)
    assert wants_log(np.array([1.0, 2.0]), True)

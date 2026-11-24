"""The parameter_space special figure on a set whose score tables are given."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from matplotlib.collections import PathCollection

from hydromodpy.display import static
from hydromodpy.display.special import parameter_space
from hydromodpy.display.subject import FigureNotApplicable
from hydromodpy.display.theme import THEMES

THEME = THEMES["default"]
K = np.array([1e-6, 1e-5, 1e-4, 1e-3])
SY = np.array([0.01, 0.05, 0.1, 0.2])


class Scored:
    """A set that hands back given tables, and records the arguments of each call."""

    def __init__(self, nan=(0, 0, 0, 0), names=("K", "Sy")):
        self.calls = []
        self.ids = [f"s{i}" for i in range(4)]
        self.nan = list(nan)
        self.names = names

    def __iter__(self):
        return iter(self.ids)

    def _params(self, table):
        table = table.copy()
        by = dict(zip(self.ids, zip(K, SY, strict=True), strict=True))
        table[self.names[0]] = [by[s][0] for s in table["sim_id"]]
        table[self.names[1]] = [by[s][1] for s in table["sim_id"]]
        return table

    def score(self, windows=None, metrics=None, months=None, station=None):
        self.calls.append(("score", windows, metrics, station))
        table = pd.DataFrame(
            {
                "sim_id": self.ids,
                "station": "gauge",
                "variable": "discharge",
                "window_name": "window",
                "metric": metrics[0],
                "value": [0.1, 0.4, 0.8, np.nan],
                "n_sim_nan": self.nan,
            }
        )
        return self._params(table)

    def score_network(self, output=None, window=None):
        self.calls.append(("network", output, window))
        rows = pd.DataFrame(
            {
                "sim_id": self.ids * 2,
                "output": "net",
                "window_name": "window",
                "bound": "maximal",
                "year": [None] * 4 + [2001] * 4,
                "quantity": "J_signed",
                "value": [3.0, 2.0, 1.0, 0.5, 9.0, 9.0, 9.0, 9.0],
            }
        )
        return self._params(rows)


def drawn(subject, **kwargs):
    ax = static.new_figure(THEME).axes[0]
    parameter_space.draw(subject, ax, THEME, **kwargs)
    return ax


def test_the_plane_is_log_log_and_coloured_by_the_metric_of_the_window():
    subject = Scored()
    ax = drawn(subject, variable=["K", "Sy", "kge"], time=["2001-01-01", "2002-01-01"], station="gauge")  # fmt: skip
    points = next(c for c in ax.collections if isinstance(c, PathCollection))
    assert (ax.get_xscale(), ax.get_yscale()) == ("log", "log")
    assert len(points.get_offsets()) == 3  # the run without a score is left out
    assert sorted(points.get_array()) == [0.1, 0.4, 0.8]
    assert subject.calls == [("score", {"window": ("2001-01-01", "2002-01-01")}, ["kge"], "gauge")]


def test_a_run_with_missing_simulated_values_is_ringed():
    ax = drawn(Scored(nan=(0, 2, 0, 0)), variable=["K", "Sy"])
    rings = [c for c in ax.collections if isinstance(c, PathCollection)][1]
    assert len(rings.get_offsets()) == 1
    assert "1 runs" in ax.get_legend().get_texts()[0].get_text()


def test_a_network_quantity_colours_the_climatological_row():
    subject = Scored()
    ax = drawn(subject, variable=["K", "Sy", "J_signed"])
    points = next(c for c in ax.collections if isinstance(c, PathCollection))
    assert sorted(points.get_array()) == [0.5, 1.0, 2.0, 3.0]
    assert subject.calls == [("network", None, None)]


def test_a_network_quantity_on_two_bounds_asks_for_one():
    subject = Scored()
    ok = subject.score_network

    def two(output=None, window=None):
        table = ok(output, window)
        return pd.concat([table, table.assign(bound="minimal")], ignore_index=True)

    subject.score_network = two
    with pytest.raises(FigureNotApplicable, match="more than once per run"):
        drawn(subject, variable=["K", "Sy", "J_signed"])
    assert drawn(subject, variable=["K", "Sy", "J_signed"], station="minimal").collections


def test_a_parameter_that_clashes_with_a_score_column_is_read_with_its_prefix():
    drawn(Scored(names=("param_K", "Sy")), variable=["K", "Sy"])


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"variable": ["K"]}, "names the two parameters"),
        ({"variable": ["K", "Sy"], "time": "last"}, "write two dates"),
        ({"variable": ["K", "porosity"]}, "parameter 'porosity'"),
        ({"variable": ["K", "Sy", "nothing"]}, "neither a metric"),
    ],
)
def test_a_figure_that_cannot_be_drawn_says_why(kwargs, match):
    with pytest.raises(FigureNotApplicable, match=match):
        drawn(Scored(), **kwargs)


def test_an_empty_set_is_not_applicable():
    subject = Scored()
    subject.ids = []
    with pytest.raises(FigureNotApplicable, match="empty"):
        drawn(subject, variable=["K", "Sy"])

"""Stiff polygon of major ions: cations at negative x, anions at positive x, in meq/L.

One row per ion pair. The tests convert mg/L to meq/L, draw the figure and read
the polygon vertices, the row order and the axis range.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.display.figures.stiff_diagram import StiffDiagramFigure

from ._hydrochem_meq import mg_to_meq

_IONS = ("Ca", "Mg", "Na", "K", "Cl", "SO4", "HCO3")


def _frame(*samples_meq: dict[str, float]) -> pd.DataFrame:
    return pd.DataFrame([{ion: s.get(ion, 0.0) for ion in _IONS} for s in samples_meq])


def _polygon_xy(ax) -> np.ndarray:
    polys = ax.patches
    assert len(polys) == 1
    return np.asarray(polys[0].get_xy())


class _ChemistryRun:
    def __init__(self, sample: dict[str, float]) -> None:
        self.sample = sample

    def timeseries(self, variable: str) -> pd.DataFrame:
        assert variable == "hydrochemistry"
        return _frame(self.sample)


class _NoChemistryRun:
    def timeseries(self, variable: str):
        raise KeyError(variable)


def test_polygon_vertices_in_meq(mpl) -> None:
    sample = mg_to_meq(
        {
            "Na": 22.990,  # monovalent -> 1 meq/L
            "K": 39.098,  # monovalent -> 1 meq/L  (Na+K row = 2 meq/L)
            "Ca": 40.078,  # divalent   -> 2 meq/L
            "Mg": 24.305,  # divalent   -> 2 meq/L
            "Cl": 35.453,  # monovalent -> 1 meq/L
            "HCO3": 61.016,  # monovalent -> 1 meq/L
            "SO4": 96.06,  # divalent   -> 2 meq/L
        }
    )
    fig, ax = mpl.subplots()

    StiffDiagramFigure().render(_frame(sample), ax)

    # Order: Na+K (y=3), Ca (y=2), Mg (y=1) on the left,
    # then SO4 (y=1), HCO3 (y=2), Cl (y=3) on the right, closing on Na+K.
    expected = [
        [-2.0, 3.0],  # -(Na+K) = -(1+1)
        [-2.0, 2.0],  # -Ca = -2
        [-2.0, 1.0],  # -Mg = -2
        [2.0, 1.0],  # +SO4 = +2
        [1.0, 2.0],  # +HCO3 = +1
        [1.0, 3.0],  # +Cl = +1
        [-2.0, 3.0],  # closure back to Na+K
    ]
    np.testing.assert_allclose(_polygon_xy(ax), expected, atol=1e-9)


def test_sample_selector(mpl) -> None:
    rows = [
        mg_to_meq({"Ca": 40.078}),  # row 0: Ca = 2 meq/L
        mg_to_meq({"Ca": 80.156}),  # row 1: Ca = 4 meq/L
    ]
    fig, ax = mpl.subplots()

    StiffDiagramFigure().render(_frame(*rows), ax, sample=1)

    # Ca is the second left vertex (y=2); row 1 has Ca = 4 meq/L.
    assert _polygon_xy(ax)[1] == pytest.approx([-4.0, 2.0])
    assert ax.get_title() == "Stiff diagram - sample 1"


XLIM = [
    # All ions tiny: the half-width clamps to 1 meq/L, so xlim spans +-1.1.
    pytest.param(mg_to_meq({"Ca": 2.0}), 1.1, id="clamped to one"),
    # HCO3 = 4 meq/L is the largest offset, so xlim spans +-4.4.
    pytest.param({"HCO3": 4.0, "Ca": 1.0}, 4.4, id="largest offset"),
]


@pytest.mark.parametrize(("sample", "half_width"), XLIM)
def test_xlim_is_symmetric(mpl, sample, half_width) -> None:
    fig, ax = mpl.subplots()

    StiffDiagramFigure().render(_frame(sample), ax)

    np.testing.assert_allclose(ax.get_xlim(), (-half_width, half_width))


def test_ylim_holds_the_three_rows(mpl) -> None:
    fig, ax = mpl.subplots()

    StiffDiagramFigure().render(_frame(mg_to_meq({"Ca": 2.0})), ax)

    assert ax.get_ylim() == pytest.approx((0.5, 3.5))


def test_reads_hydrochemistry_from_the_run(mpl) -> None:
    fig, ax = mpl.subplots()

    StiffDiagramFigure().render(_ChemistryRun(mg_to_meq({"Ca": 40.078, "Cl": 35.453})), ax)

    xy = _polygon_xy(ax)
    assert xy[1] == pytest.approx([-2.0, 2.0])  # Ca = 2 meq/L on the left
    assert xy[5] == pytest.approx([1.0, 3.0])  # Cl = 1 meq/L on the right


REFUSALS = [
    pytest.param(object(), TypeError, "cannot read hydrochemistry data", id="not a table"),
    pytest.param(
        _NoChemistryRun(), ValueError, "no hydrochemistry data available", id="run without data"
    ),
]


@pytest.mark.parametrize(("data", "error", "message"), REFUSALS)
def test_refusals(mpl, data, error, message) -> None:
    fig, ax = mpl.subplots()

    with pytest.raises(error, match=message):
        StiffDiagramFigure().render(data, ax)

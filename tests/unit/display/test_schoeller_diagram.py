"""Schoeller profile of major ions: one polyline per sample, meq/L on a log y-axis.

The tests convert mg/L to meq/L, draw the figure and read the line values and the
ion order.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.display.figures.schoeller_diagram import SchoellerDiagramFigure

from ._hydrochem_meq import mg_to_meq

_IONS = ("Ca", "Mg", "Na", "K", "Cl", "SO4", "HCO3")


def _frame(*samples_meq: dict[str, float]) -> pd.DataFrame:
    return pd.DataFrame([{ion: s.get(ion, 0.0) for ion in _IONS} for s in samples_meq])


class _ChemistryRun:
    def __init__(self, sample: dict[str, float]) -> None:
        self.sample = sample

    def timeseries(self, variable: str) -> pd.DataFrame:
        assert variable == "hydrochemistry"
        return _frame(self.sample)


class _NoChemistryRun:
    def timeseries(self, variable: str):
        raise KeyError(variable)


def test_line_y_values_equal_meq_per_ion(mpl) -> None:
    sample = mg_to_meq({"Ca": 40.078, "Mg": 24.305, "Na": 22.990, "Cl": 35.453, "HCO3": 61.016})
    fig, ax = mpl.subplots()

    SchoellerDiagramFigure().render(_frame(sample), ax)

    line = ax.lines[0]
    assert line.get_xdata().tolist() == list(range(len(_IONS)))
    # Ca/Mg are divalent: 40.078 mg/L -> 2 meq/L, 24.305 mg/L -> 2 meq/L.
    # Na, Cl, HCO3 are monovalent at 1 equivalent mass -> 1 meq/L. K, SO4 zero -> nan.
    np.testing.assert_allclose(line.get_ydata(), [2.0, 2.0, 1.0, np.nan, 1.0, np.nan, 1.0])


def test_nonpositive_concentrations_are_masked(mpl) -> None:
    df = _frame({ion: 1.0 for ion in _IONS})
    df.loc[0, "Ca"] = 0.0
    df.loc[0, "Mg"] = -3.0
    fig, ax = mpl.subplots()

    SchoellerDiagramFigure().render(df, ax)

    y = ax.lines[0].get_ydata()
    assert np.isnan(y[0])  # Ca == 0
    assert np.isnan(y[1])  # Mg < 0
    assert y[2] == pytest.approx(1.0)  # Na > 0 kept


def test_reads_hydrochemistry_from_the_run(mpl) -> None:
    fig, ax = mpl.subplots()

    SchoellerDiagramFigure().render(_ChemistryRun(mg_to_meq({"Na": 22.990, "Cl": 35.453})), ax)

    y = ax.lines[0].get_ydata()
    assert y[2] == pytest.approx(1.0)  # Na
    assert y[4] == pytest.approx(1.0)  # Cl
    assert np.isnan(y[0])  # Ca absent


REFUSALS = [
    pytest.param(
        pd.DataFrame([{ion: 1.0 for ion in _IONS if ion != "K"}]),
        KeyError,
        "missing columns",
        id="missing ion column",
    ),
    pytest.param(object(), TypeError, "cannot read hydrochemistry data", id="not a table"),
    pytest.param(
        _NoChemistryRun(), ValueError, "no hydrochemistry data available", id="run without data"
    ),
]


@pytest.mark.parametrize(("data", "error", "message"), REFUSALS)
def test_refusals(mpl, data, error, message) -> None:
    fig, ax = mpl.subplots()

    with pytest.raises(error, match=message):
        SchoellerDiagramFigure().render(data, ax)

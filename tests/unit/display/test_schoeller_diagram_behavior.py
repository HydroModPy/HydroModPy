"""Behavioral coverage for the Schoeller diagram builder.

The Schoeller profile plots meq/L concentration per ion on a log y-axis,
one polyline per sample. Tests convert mg/L to meq/L, drive the real
:class:`SchoellerDiagramFigure`, and assert axis ordering and line values.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.display.figures.schoeller_diagram import SchoellerDiagramFigure

from ._hydrochem_meq import mg_to_meq

_IONS = ("Ca", "Mg", "Na", "K", "Cl", "SO4", "HCO3")


@pytest.fixture
def mpl():
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    yield plt
    plt.close("all")


def _frame(*samples_meq: dict[str, float]) -> pd.DataFrame:
    return pd.DataFrame([{ion: s.get(ion, 0.0) for ion in _IONS} for s in samples_meq])


def test_log_axis_with_ions_in_fixed_left_to_right_order(mpl) -> None:
    sample = mg_to_meq({ion: 50.0 for ion in _IONS})
    fig, ax = mpl.subplots()

    SchoellerDiagramFigure().render(_frame(sample), ax)

    try:
        assert ax.get_yscale() == "log"
        assert [t.get_text() for t in ax.get_xticklabels()] == list(_IONS)
        assert ax.get_xticks().tolist() == list(range(len(_IONS)))
        assert ax.get_ylabel() == "Concentration (meq/L)"
    finally:
        mpl.close(fig)


def test_line_y_values_equal_meq_per_ion(mpl) -> None:
    sample_mg = {"Ca": 40.078, "Mg": 24.305, "Na": 22.990, "Cl": 35.453, "HCO3": 61.016}
    sample = mg_to_meq(sample_mg)
    fig, ax = mpl.subplots()

    SchoellerDiagramFigure().render(_frame(sample), ax)

    try:
        line = ax.lines[0]
        assert line.get_xdata().tolist() == list(range(len(_IONS)))
        ydata = line.get_ydata()
        # Ca/Mg are divalent: 40.078 mg/L -> 2 meq/L, 24.305 mg/L -> 2 meq/L.
        # Na, Cl, HCO3 are monovalent at 1 equivalent mass -> 1 meq/L. K, SO4 zero -> nan.
        expected = [2.0, 2.0, 1.0, np.nan, 1.0, np.nan, 1.0]
        np.testing.assert_allclose(ydata, expected)
    finally:
        mpl.close(fig)


def test_one_polyline_drawn_per_sample(mpl) -> None:
    rows = [
        mg_to_meq({"Ca": 40.0, "HCO3": 120.0}),
        mg_to_meq({"Na": 30.0, "Cl": 50.0}),
        mg_to_meq({"Mg": 20.0, "SO4": 96.06}),
    ]
    fig, ax = mpl.subplots()

    SchoellerDiagramFigure().render(_frame(*rows), ax)

    try:
        assert len(ax.lines) == 3
        # Second sample: only Na and Cl positive, the rest masked to nan.
        y_na_cl = ax.lines[1].get_ydata()
        assert np.isnan(y_na_cl[0])  # Ca
        assert not np.isnan(y_na_cl[2])  # Na
        assert not np.isnan(y_na_cl[4])  # Cl
        assert np.isnan(y_na_cl[6])  # HCO3
    finally:
        mpl.close(fig)


def test_nonpositive_concentrations_are_masked_to_nan(mpl) -> None:
    df = _frame({ion: 1.0 for ion in _IONS})
    df.loc[0, "Ca"] = 0.0
    df.loc[0, "Mg"] = -3.0
    fig, ax = mpl.subplots()

    SchoellerDiagramFigure().render(df, ax)

    try:
        y = ax.lines[0].get_ydata()
        assert np.isnan(y[0])  # Ca == 0
        assert np.isnan(y[1])  # Mg < 0
        assert y[2] == pytest.approx(1.0)  # Na > 0 kept
    finally:
        mpl.close(fig)


def test_missing_ion_column_raises_keyerror(mpl) -> None:
    df = pd.DataFrame([{ion: 1.0 for ion in _IONS if ion != "K"}])
    fig, ax = mpl.subplots()

    try:
        with pytest.raises(KeyError, match="missing columns"):
            SchoellerDiagramFigure().render(df, ax)
    finally:
        mpl.close(fig)


def test_non_dataframe_without_timeseries_raises_typeerror(mpl) -> None:
    fig, ax = mpl.subplots()

    try:
        with pytest.raises(TypeError, match="cannot read data"):
            SchoellerDiagramFigure().render(object(), ax)
    finally:
        mpl.close(fig)


def test_reads_hydrochemistry_via_run_timeseries_hook(mpl) -> None:
    sample = mg_to_meq({"Na": 22.990, "Cl": 35.453})

    class _Run:
        def timeseries(self, variable: str) -> pd.DataFrame:
            assert variable == "hydrochemistry"
            return _frame(sample)

    fig, ax = mpl.subplots()

    SchoellerDiagramFigure().render(_Run(), ax)

    try:
        y = ax.lines[0].get_ydata()
        assert y[2] == pytest.approx(1.0)  # Na
        assert y[4] == pytest.approx(1.0)  # Cl
        assert np.isnan(y[0])  # Ca absent
    finally:
        mpl.close(fig)


def test_run_without_hydrochemistry_raises_valueerror(mpl) -> None:
    class _Run:
        def timeseries(self, variable: str):
            raise KeyError(variable)

    fig, ax = mpl.subplots()

    try:
        with pytest.raises(ValueError, match="no hydrochemistry data available"):
            SchoellerDiagramFigure().render(_Run(), ax)
    finally:
        mpl.close(fig)

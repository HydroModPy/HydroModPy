"""Behavioral coverage for the Stiff diagram builder.

The Stiff polygon places cations at negative x (left) and anions at
positive x (right), one row per ion pair. Tests convert mg/L to meq/L,
drive the real :class:`StiffDiagramFigure`, and assert the polygon
vertex offsets, the row ordering and the axis range.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.display.figures.stiff_diagram import StiffDiagramFigure

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


def _polygon_xy(ax) -> np.ndarray:
    polys = ax.patches
    assert len(polys) == 1
    return np.asarray(polys[0].get_xy())


def test_polygon_vertices_match_meq_offsets_left_and_right(mpl) -> None:
    sample_mg = {
        "Na": 22.990,  # monovalent -> 1 meq/L
        "K": 39.098,  # monovalent -> 1 meq/L  (Na+K row = 2 meq/L)
        "Ca": 40.078,  # divalent   -> 2 meq/L
        "Mg": 24.305,  # divalent   -> 2 meq/L
        "Cl": 35.453,  # monovalent -> 1 meq/L
        "HCO3": 61.016,  # monovalent -> 1 meq/L
        "SO4": 96.06,  # divalent   -> 2 meq/L
    }
    sample = mg_to_meq(sample_mg)
    fig, ax = mpl.subplots()

    StiffDiagramFigure().render(_frame(sample), ax)

    try:
        xy = _polygon_xy(ax)
        # Order: Na+K (y=3), Ca (y=2), Mg (y=1) on the left,
        # then SO4 (y=1), HCO3 (y=2), Cl (y=3) on the right, closing on Na+K.
        expected = np.array(
            [
                [-2.0, 3.0],  # -(Na+K) = -(1+1)
                [-2.0, 2.0],  # -Ca = -2
                [-2.0, 1.0],  # -Mg = -2
                [2.0, 1.0],  # +SO4 = +2
                [1.0, 2.0],  # +HCO3 = +1
                [1.0, 3.0],  # +Cl = +1
                [-2.0, 3.0],  # closure back to Na+K
            ]
        )
        np.testing.assert_allclose(xy, expected, atol=1e-9)
    finally:
        mpl.close(fig)


def test_cations_sit_left_anions_sit_right_of_axis(mpl) -> None:
    sample = mg_to_meq({"Na": 60.0, "Ca": 80.0, "Mg": 24.0, "Cl": 70.0, "HCO3": 150.0, "SO4": 96.0})
    fig, ax = mpl.subplots()

    StiffDiagramFigure().render(_frame(sample), ax)

    try:
        xy = _polygon_xy(ax)[:-1]  # drop closure vertex
        left = xy[:3, 0]
        right = xy[3:, 0]
        assert np.all(left < 0.0)
        assert np.all(right > 0.0)
    finally:
        mpl.close(fig)


def test_sample_selector_picks_the_requested_row(mpl) -> None:
    rows = [
        mg_to_meq({"Ca": 40.078}),  # row 0: Ca = 2 meq/L
        mg_to_meq({"Ca": 80.156}),  # row 1: Ca = 4 meq/L
    ]
    fig, ax = mpl.subplots()

    StiffDiagramFigure().render(_frame(*rows), ax, sample=1)

    try:
        xy = _polygon_xy(ax)
        # Ca is the second left vertex (y=2); row 1 has Ca = 4 meq/L.
        assert xy[1] == pytest.approx([-4.0, 2.0])
        assert ax.get_title() == "Stiff diagram - sample 1"
    finally:
        mpl.close(fig)


def test_xlim_is_symmetric_and_clamped_to_at_least_unit(mpl) -> None:
    # All ions tiny -> max_side clamps to 1.0, so xlim spans +-1.1.
    sample = mg_to_meq({"Ca": 2.0})
    fig, ax = mpl.subplots()

    StiffDiagramFigure().render(_frame(sample), ax)

    try:
        lo, hi = ax.get_xlim()
        assert lo == pytest.approx(-1.1)
        assert hi == pytest.approx(1.1)
        assert ax.get_ylim() == pytest.approx((0.5, 3.5))
    finally:
        mpl.close(fig)


def test_xlim_scales_with_largest_ion_offset(mpl) -> None:
    # HCO3 = 4 meq/L is the largest offset -> xlim spans +-4.4.
    sample = {"HCO3": 4.0, "Ca": 1.0}
    fig, ax = mpl.subplots()

    StiffDiagramFigure().render(_frame(sample), ax)

    try:
        lo, hi = ax.get_xlim()
        assert hi == pytest.approx(4.4)
        assert lo == pytest.approx(-4.4)
    finally:
        mpl.close(fig)


def test_non_dataframe_without_timeseries_raises_typeerror(mpl) -> None:
    fig, ax = mpl.subplots()

    try:
        with pytest.raises(TypeError, match="cannot read data"):
            StiffDiagramFigure().render(object(), ax)
    finally:
        mpl.close(fig)


def test_reads_hydrochemistry_via_run_timeseries_hook(mpl) -> None:
    sample = mg_to_meq({"Ca": 40.078, "Cl": 35.453})

    class _Run:
        def timeseries(self, variable: str) -> pd.DataFrame:
            assert variable == "hydrochemistry"
            return _frame(sample)

    fig, ax = mpl.subplots()

    StiffDiagramFigure().render(_Run(), ax)

    try:
        xy = _polygon_xy(ax)
        assert xy[1] == pytest.approx([-2.0, 2.0])  # Ca = 2 meq/L on the left
        assert xy[5] == pytest.approx([1.0, 3.0])  # Cl = 1 meq/L on the right
    finally:
        mpl.close(fig)


def test_run_without_hydrochemistry_raises_valueerror(mpl) -> None:
    class _Run:
        def timeseries(self, variable: str):
            raise KeyError(variable)

    fig, ax = mpl.subplots()

    try:
        with pytest.raises(ValueError, match="no hydrochemistry data available"):
            StiffDiagramFigure().render(_Run(), ax)
    finally:
        mpl.close(fig)


def test_row_labels_pair_cation_and_anion(mpl) -> None:
    sample = mg_to_meq({"Ca": 40.0, "Cl": 50.0})
    fig, ax = mpl.subplots()

    StiffDiagramFigure().render(_frame(sample), ax)

    try:
        assert ax.get_yticks().tolist() == [1, 2, 3]
        assert [t.get_text() for t in ax.get_yticklabels()] == [
            "Mg | SO4",
            "Ca | HCO3",
            "Na+K | Cl",
        ]
        assert ax.get_xlabel() == "meq/L"
    finally:
        mpl.close(fig)

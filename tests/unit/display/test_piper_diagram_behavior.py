"""Behavioral coverage for the Piper diagram builder.

The builder consumes meq/L (see module docstring). Each test converts a
mg/L sample to meq/L, drives the real :class:`PiperDiagramFigure`, and
asserts the trilinear/diamond geometry on the returned scatter offsets.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from hydromodpy.display.figures.piper_diagram import PiperDiagramFigure

from ._hydrochem_meq import mg_to_meq

_SQRT3 = math.sqrt(3.0)
_MAJORS = ("Ca", "Mg", "Na", "K", "Cl", "SO4", "HCO3")


@pytest.fixture
def mpl():
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    yield plt
    plt.close("all")


def _frame(*samples_meq: dict[str, float]) -> pd.DataFrame:
    return pd.DataFrame([{ion: s.get(ion, 0.0) for ion in _MAJORS} for s in samples_meq])


def _offsets_by_label(ax) -> dict[str, np.ndarray]:
    out: dict[str, np.ndarray] = {}
    for coll in ax.collections:
        out[coll.get_label()] = np.asarray(coll.get_offsets())
    return out


def test_mg_to_meq_conversion_uses_valence_weighted_equivalents() -> None:
    # Ca 40 mg/L over equiv weight 20.039 -> ~1.996 meq/L; SO4 divides by 48.03.
    meq = mg_to_meq({"Ca": 40.078, "Na": 22.990, "SO4": 96.06})
    assert meq["Ca"] == pytest.approx(2.0)
    assert meq["Na"] == pytest.approx(1.0)
    assert meq["SO4"] == pytest.approx(2.0)


def test_pure_calcium_sample_plots_at_cation_ca_vertex(mpl) -> None:
    # 100 mg/L Ca only: after meq/L normalization the cation point must land
    # at the left-triangle Ca vertex (0, 0).
    sample = mg_to_meq({"Ca": 100.0, "Cl": 100.0})
    fig, ax = mpl.subplots()

    PiperDiagramFigure().render(_frame(sample), ax)

    try:
        offsets = _offsets_by_label(ax)
        cat = offsets["cations"][0]
        assert cat == pytest.approx([0.0, 0.0])
        # And the matching pure-Cl anion lands at the right-triangle Cl vertex.
        an = offsets["anions"][0]
        assert an == pytest.approx([3.0, 0.0])
    finally:
        mpl.close(fig)


def test_cation_end_members_land_on_their_ternary_vertices(mpl) -> None:
    # One row per cation end-member, anion held constant (pure HCO3).
    rows = [
        mg_to_meq({"Ca": 80.0, "HCO3": 200.0}),
        mg_to_meq({"Mg": 24.305, "HCO3": 200.0}),
        mg_to_meq({"Na": 50.0, "HCO3": 200.0}),
        mg_to_meq({"K": 40.0, "HCO3": 200.0}),
    ]
    fig, ax = mpl.subplots()

    PiperDiagramFigure().render(_frame(*rows), ax)

    try:
        cat = _offsets_by_label(ax)["cations"]
        assert cat[0] == pytest.approx([0.0, 0.0])  # Ca vertex
        assert cat[1] == pytest.approx([0.5, _SQRT3 / 2])  # Mg apex
        assert cat[2] == pytest.approx([1.0, 0.0])  # Na+K vertex
        assert cat[3] == pytest.approx([1.0, 0.0])  # K also maps to Na+K vertex
    finally:
        mpl.close(fig)


def test_anion_end_members_land_on_their_ternary_vertices(mpl) -> None:
    rows = [
        mg_to_meq({"Ca": 80.0, "HCO3": 200.0}),
        mg_to_meq({"Ca": 80.0, "Cl": 100.0}),
        mg_to_meq({"Ca": 80.0, "SO4": 96.06}),
    ]
    fig, ax = mpl.subplots()

    PiperDiagramFigure().render(_frame(*rows), ax)

    try:
        an = _offsets_by_label(ax)["anions"]
        assert an[0] == pytest.approx([2.0, 0.0])  # HCO3 vertex
        assert an[1] == pytest.approx([3.0, 0.0])  # Cl vertex
        assert an[2] == pytest.approx([2.5, _SQRT3 / 2])  # SO4 apex
    finally:
        mpl.close(fig)


def test_balanced_mix_centroid_matches_normalized_fractions(mpl) -> None:
    # Equal meq of every cation and every anion -> centroid of each triangle.
    sample = {
        "Ca": 1.0,
        "Mg": 1.0,
        "Na": 1.0,
        "K": 1.0,
        "Cl": 1.0,
        "SO4": 1.0,
        "HCO3": 1.0,
    }
    fig, ax = mpl.subplots()

    PiperDiagramFigure().render(_frame(sample), ax)

    try:
        offsets = _offsets_by_label(ax)
        cat = offsets["cations"][0]
        # Fractions: Ca=Mg=1/4, Na+K=1/2. xL=0.5*(2*0.5+0.25)=0.625, yL=sqrt3/2*0.25.
        assert cat == pytest.approx([0.625, (_SQRT3 / 2) * 0.25])
        an = offsets["anions"][0]
        # Cl=SO4=HCO3=1/3. xR=2+0.5*(2/3+1/3)=2.5, yR=sqrt3/2*(1/3).
        assert an == pytest.approx([2.5, (_SQRT3 / 2) * (1.0 / 3.0)])
    finally:
        mpl.close(fig)


def test_zero_total_sample_does_not_divide_by_zero(mpl) -> None:
    fig, ax = mpl.subplots()

    PiperDiagramFigure().render(_frame({}), ax)

    try:
        offsets = _offsets_by_label(ax)
        assert np.all(np.isfinite(offsets["cations"]))
        assert np.all(np.isfinite(offsets["anions"]))
    finally:
        mpl.close(fig)


def test_three_scatter_collections_and_frame_lines_are_drawn(mpl) -> None:
    sample = mg_to_meq({"Ca": 50.0, "Mg": 20.0, "Cl": 60.0, "HCO3": 120.0})
    fig, ax = mpl.subplots()

    PiperDiagramFigure().render(_frame(sample), ax)

    try:
        labels = [c.get_label() for c in ax.collections]
        assert labels == ["cations", "anions", "facies"]
        # tri_left, tri_right and the diamond frame -> three plotted outlines.
        assert len(ax.lines) == 3
        assert ax.get_title() == "Piper diagram"
    finally:
        mpl.close(fig)


def test_missing_major_column_raises_keyerror(mpl) -> None:
    df = pd.DataFrame([{ion: 1.0 for ion in _MAJORS if ion != "HCO3"}])
    fig, ax = mpl.subplots()

    try:
        with pytest.raises(KeyError, match="missing columns"):
            PiperDiagramFigure().render(df, ax)
    finally:
        mpl.close(fig)


def test_non_dataframe_without_timeseries_raises_typeerror(mpl) -> None:
    fig, ax = mpl.subplots()

    try:
        with pytest.raises(TypeError, match="cannot read hydrochem data"):
            PiperDiagramFigure().render(object(), ax)
    finally:
        mpl.close(fig)


def test_reads_hydrochemistry_via_run_timeseries_hook(mpl) -> None:
    sample = mg_to_meq({"Ca": 100.0, "HCO3": 200.0})

    class _Run:
        def timeseries(self, variable: str) -> pd.DataFrame:
            assert variable == "hydrochemistry"
            return _frame(sample)

    fig, ax = mpl.subplots()

    PiperDiagramFigure().render(_Run(), ax)

    try:
        # Pure-Ca / pure-HCO3 still resolve to the expected vertices.
        offsets = _offsets_by_label(ax)
        assert offsets["cations"][0] == pytest.approx([0.0, 0.0])
        assert offsets["anions"][0] == pytest.approx([2.0, 0.0])
    finally:
        mpl.close(fig)


def test_run_without_hydrochemistry_raises_valueerror(mpl) -> None:
    class _Run:
        def timeseries(self, variable: str):
            raise KeyError(variable)

    fig, ax = mpl.subplots()

    try:
        with pytest.raises(ValueError, match="no hydrochemistry data available"):
            PiperDiagramFigure().render(_Run(), ax)
    finally:
        mpl.close(fig)

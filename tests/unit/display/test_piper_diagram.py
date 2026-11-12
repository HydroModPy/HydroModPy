"""Piper diagram of major ions, plotted from meq/L on two ternary triangles and a diamond.

Cations (Ca, Mg, Na+K) plot on the left triangle and anions (HCO3, Cl, SO4) on
the right one. Each ion is normalized by the sum of its family, so a point
depends on relative meq/L only. Tests convert mg/L to meq/L first.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from hydromodpy.display.figures.piper_diagram import PiperDiagramFigure

from ._hydrochem_meq import mg_to_meq

SQRT3_2 = math.sqrt(3.0) / 2
MAJORS = ("Ca", "Mg", "Na", "K", "Cl", "SO4", "HCO3")


def meq_frame(*samples_meq: dict[str, float]) -> pd.DataFrame:
    return pd.DataFrame([{ion: s.get(ion, 0.0) for ion in MAJORS} for s in samples_meq])


def offsets_by_label(ax) -> dict[str, np.ndarray]:
    return {coll.get_label(): np.asarray(coll.get_offsets()) for coll in ax.collections}


def test_mg_to_meq_uses_valence_weighted_equivalents() -> None:
    # Ca 40.078 mg/L over equivalent weight 20.039 mg/meq is 2 meq/L, SO4 divides by 48.03.
    meq = mg_to_meq({"Ca": 40.078, "Na": 22.990, "SO4": 96.06})

    assert meq["Ca"] == pytest.approx(2.0)
    assert meq["Na"] == pytest.approx(1.0)
    assert meq["SO4"] == pytest.approx(2.0)


# One sample per row, anion held at pure HCO3 for the cations and pure Ca for the anions.
VERTICES = [
    pytest.param(
        [mg_to_meq({"Ca": 100.0, "Cl": 100.0})],
        "cations",
        [[0.0, 0.0]],
        id="pure Ca on the Ca vertex",
    ),
    pytest.param(
        [mg_to_meq({"Ca": 100.0, "Cl": 100.0})],
        "anions",
        [[3.0, 0.0]],
        id="pure Cl on the Cl vertex",
    ),
    pytest.param(
        [
            mg_to_meq({"Ca": 80.0, "HCO3": 200.0}),
            mg_to_meq({"Mg": 24.305, "HCO3": 200.0}),
            mg_to_meq({"Na": 50.0, "HCO3": 200.0}),
            mg_to_meq({"K": 40.0, "HCO3": 200.0}),
        ],
        "cations",
        # Ca vertex, Mg apex, then Na and K both on the Na+K vertex.
        [[0.0, 0.0], [0.5, SQRT3_2], [1.0, 0.0], [1.0, 0.0]],
        id="cation end members",
    ),
    pytest.param(
        [
            mg_to_meq({"Ca": 80.0, "HCO3": 200.0}),
            mg_to_meq({"Ca": 80.0, "Cl": 100.0}),
            mg_to_meq({"Ca": 80.0, "SO4": 96.06}),
        ],
        "anions",
        # HCO3 vertex, Cl vertex, SO4 apex.
        [[2.0, 0.0], [3.0, 0.0], [2.5, SQRT3_2]],
        id="anion end members",
    ),
    pytest.param(
        [dict.fromkeys(MAJORS, 1.0)],
        "cations",
        # Ca = Mg = 1/4 and Na+K = 1/2, so x = 0.5 * (2 * 0.5 + 0.25) and y = sqrt(3)/2 * 0.25.
        [[0.625, SQRT3_2 * 0.25]],
        id="balanced mix, cation centroid",
    ),
    pytest.param(
        [dict.fromkeys(MAJORS, 1.0)],
        "anions",
        # Cl = SO4 = HCO3 = 1/3, so x = 2 + 0.5 * (2/3 + 1/3) and y = sqrt(3)/2 / 3.
        [[2.5, SQRT3_2 / 3.0]],
        id="balanced mix, anion centroid",
    ),
]


@pytest.mark.parametrize(("samples", "family", "expected"), VERTICES)
def test_sample_position_on_a_triangle(mpl, samples, family, expected) -> None:
    fig, ax = mpl.subplots()

    PiperDiagramFigure().render(meq_frame(*samples), ax)

    np.testing.assert_allclose(offsets_by_label(ax)[family], expected, atol=1e-9)


def test_hydrochemistry_is_read_from_the_run_timeseries(mpl) -> None:
    class Run:
        def timeseries(self, variable: str) -> pd.DataFrame:
            assert variable == "hydrochemistry"
            return meq_frame(mg_to_meq({"Ca": 100.0, "HCO3": 200.0}))

    fig, ax = mpl.subplots()

    PiperDiagramFigure().render(Run(), ax)

    offsets = offsets_by_label(ax)
    assert offsets["cations"][0] == pytest.approx([0.0, 0.0])
    assert offsets["anions"][0] == pytest.approx([2.0, 0.0])


class RunWithoutHydrochemistry:
    def timeseries(self, variable: str):
        raise KeyError(variable)


REFUSALS = [
    pytest.param(
        pd.DataFrame([{ion: 1.0 for ion in MAJORS if ion != "HCO3"}]),
        KeyError,
        "missing columns",
        id="missing major column",
    ),
    pytest.param(object(), TypeError, "cannot read hydrochemistry data", id="not a table"),
    pytest.param(
        RunWithoutHydrochemistry(),
        ValueError,
        "no hydrochemistry data available",
        id="run without hydrochemistry",
    ),
]


@pytest.mark.parametrize(("data", "error", "message"), REFUSALS)
def test_refusals(mpl, data, error, message) -> None:
    fig, ax = mpl.subplots()

    with pytest.raises(error, match=message):
        PiperDiagramFigure().render(data, ax)

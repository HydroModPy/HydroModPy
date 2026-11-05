"""Tests of `criteria.formulas`."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.calibration.criteria.formulas import METRIC_FORMULAS
from hydromodpy.core.scoring import metrics as core

# From test_kge_is_written_as_the_2009_form.py
# The KGE of HydroModPy is the 2009 form, and every place that describes it says so.
#
# Every KGE here (``kge``, ``kge_r``, ``kge_alpha``, ``kge_beta``) uses
# ``beta = sum(s) / sum(o)`` and ``alpha = std(s) / std(o)`` (Gupta et al., 2009).
# The 2012 form (``alpha`` as a ratio of coefficients of variation) gives another
# number on the same series, 0.9207 against 0.8821 on the audit probe (N13 of the
# audit of 2026-10-20, decision m14), and nothing said which one was meant.


def test_the_kernel_is_the_2009_form() -> None:
    obs = np.array([5.0, 3.0, 2.0, 1.2, 0.8, 0.5, 0.3, 0.2, 0.15, 0.1])
    sim = obs * np.array([1.1, 0.9, 1.05, 0.95, 1.2, 0.85, 1.1, 0.9, 1.3, 0.8])

    parts = core.kge(sim, obs)

    assert parts["beta"] == pytest.approx(sim.sum() / obs.sum())
    assert parts["alpha"] == pytest.approx(sim.std() / obs.std())
    cv_ratio = (sim.std() / sim.mean()) / (obs.std() / obs.mean())
    assert parts["alpha"] != pytest.approx(cv_ratio)


def test_the_formula_of_the_registry_says_kge_2009() -> None:
    formula = METRIC_FORMULAS["kge"]

    assert "2009" in formula.note
    assert "2012" in formula.note

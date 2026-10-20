"""The KGE of HydroModPy is the 2009 form, and every place that describes it says so.

Every KGE here (``kge``, ``kge_r``, ``kge_alpha``, ``kge_beta``) uses
``beta = sum(s) / sum(o)`` and ``alpha = std(s) / std(o)`` (Gupta et al., 2009).
The 2012 form (``alpha`` as a ratio of coefficients of variation) gives another
number on the same series, 0.9207 against 0.8821 on the audit probe (N13 of the
audit of 2026-10-20, decision m14), and nothing said which one was meant.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import yaml

from hydromodpy.calibration.criteria.formulas import METRIC_FORMULAS
from hydromodpy.core import metrics as core

ROOT = Path(__file__).resolve().parents[3]


def test_the_kernel_is_the_2009_form() -> None:
    obs = np.array([5.0, 3.0, 2.0, 1.2, 0.8, 0.5, 0.3, 0.2, 0.15, 0.1])
    sim = obs * np.array([1.1, 0.9, 1.05, 0.95, 1.2, 0.85, 1.1, 0.9, 1.3, 0.8])

    parts = core.kge(sim, obs)

    assert parts["beta"] == pytest.approx(sim.sum() / obs.sum())
    assert parts["alpha"] == pytest.approx(sim.std() / obs.std())
    cv_ratio = (sim.std() / sim.mean()) / (obs.std() / obs.mean())
    assert parts["alpha"] != pytest.approx(cv_ratio)


def test_the_kernel_docstring_names_the_form() -> None:
    doc = core.kge.__doc__ or ""

    assert "2009" in doc
    assert "sum" in doc.lower()
    assert "2012" in doc


def test_the_formula_of_the_registry_says_kge_2009() -> None:
    formula = METRIC_FORMULAS["kge"]

    assert "2009" in formula.note
    assert "2012" in formula.note


def test_the_symbol_of_the_theory_page_says_kge_2009() -> None:
    symbols = yaml.safe_load((ROOT / "docs/source/theory/symbols.yaml").read_text("utf-8"))
    entries = symbols["symbols"] if isinstance(symbols, dict) else symbols
    kge = next(entry for entry in entries if entry["id"] == "kge")

    assert "2009" in kge["meaning"]

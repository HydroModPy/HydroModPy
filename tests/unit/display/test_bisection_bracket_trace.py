"""Trace of the residual J = D_so - D_os (m) and of the bracket a bisection closes on a root.

A session is one row per trial, with the sampled parameter under ``parameters``
and the criterion diagnostics under ``components``. A root is bracketed once
two trials give residuals of opposite sign.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.display.figures.bisection_bracket_trace import (
    BisectionBracketTraceFigure,
    _running_bracket,
)
from hydromodpy.results.session.view import Session

from ._calibration_journal import (
    K_BOUNDS,
    TWO_ROOT_CONFIG,
    TWO_ROOT_J,
    TWO_ROOTS,
    journal_session,
    two_root_rows,
)

H_OBS = 250.0
NO_DISTANCE = {"D_so": None, "D_os": None}


def diagnostic(j_signed: float) -> dict[str, float]:
    return {"D_so": 0.0, "D_os": 0.0, "J_signed": j_signed}


def session_run(project: Path, parameter_values: list[float], diagnostics: list[dict]) -> Session:
    """One bisection session. A trial with no distance is recorded as failed."""
    rows = []
    for index, (value, diag) in enumerate(zip(parameter_values, diagnostics, strict=True)):
        payload = {f"streams.{key}": number for key, number in diag.items() if number is not None}
        payload["streams.h_obs"] = H_OBS
        rows.append(
            {
                "trial": index + 1,
                "parameters": {"K_over_R": {"value": value}},
                "components": payload,
                "status": "completed" if diag.get("D_os") is not None else "failed",
            }
        )
    return journal_session(project / uuid.uuid4().hex, rows, name="cheze-bisection")


def bracket_run(project: Path) -> Session:
    """A sweep that changes sign once, then two bisection steps closing on it."""
    return session_run(
        project,
        [1e-5, 1e-3, 1e-4, 3.2e-5],
        [diagnostic(300.0), diagnostic(-400.0), diagnostic(-120.0), diagnostic(40.0)],
    )


def two_root_run(tmp_path) -> Session:
    return journal_session(
        tmp_path,
        two_root_rows(),
        method="bisection",
        phase="transient_conductivity",
        config=TWO_ROOT_CONFIG,
        bounds=K_BOUNDS,
        best_trial=24,
        root_search=TWO_ROOTS,
    )


def test_running_bracket_only_tightens() -> None:
    values = np.array([1e-5, 1e-3, 1e-4, 3.2e-5])
    residual = np.array([300.0, -400.0, -120.0, 40.0])

    trace = _running_bracket(values, residual)

    # Nothing brackets the first point. The second opens [1e-5, 1e-3] and each
    # following evaluation lands inside and tightens it.
    assert not np.isfinite(trace.parameter_low[0])
    assert trace.parameter_low[1] == pytest.approx(1e-5)
    assert trace.parameter_high[1] == pytest.approx(1e-3)
    assert trace.parameter_high[2] == pytest.approx(1e-4)
    assert trace.parameter_low[3] == pytest.approx(3.2e-5)
    widths = trace.residual_high[1:] - trace.residual_low[1:]
    assert list(widths) == sorted(widths, reverse=True)
    assert trace.is_closed


def test_note_names_the_closed_bracket(mpl, tmp_path) -> None:
    _, ax = mpl.subplots()

    BisectionBracketTraceFigure().render(bracket_run(tmp_path), ax)

    note = ax.texts[0].get_text()
    assert "K_over_R in [3.2e-05, 0.0001]" in note
    assert "factor" in note


def test_no_sign_change_is_named(mpl, tmp_path) -> None:
    run = session_run(
        tmp_path, [1e-5, 1e-4, 1e-3], [diagnostic(300.0), diagnostic(120.0), diagnostic(40.0)]
    )
    _, ax = mpl.subplots()

    BisectionBracketTraceFigure().render(run, ax)

    assert "no sign change: no root is bracketed" in ax.texts[0].get_text()
    labels = [text.get_text() for text in ax.get_legend().get_texts()]
    assert not any(label.startswith("bracket") for label in labels)


def test_failed_evaluation_stays_on_the_zero_line(mpl, tmp_path) -> None:
    run = session_run(
        tmp_path, [1e-5, 1e-4, 1e-3], [diagnostic(300.0), NO_DISTANCE, diagnostic(-40.0)]
    )
    _, ax = mpl.subplots()

    BisectionBracketTraceFigure().render(run, ax)

    failed = next(
        item for item in ax.collections if str(item.get_label()).startswith("failed evaluation")
    )
    assert failed.get_offsets().tolist() == [[2.0, 0.0]]


def test_two_bounds_draw_both_residuals_brackets_and_roots(mpl, tmp_path) -> None:
    _, ax = mpl.subplots()

    BisectionBracketTraceFigure().render(two_root_run(tmp_path), ax)

    for bound in ("minimal", "maximal"):
        series = next(
            item for item in ax.collections if item.get_label() == f"D_so - D_os, {bound} bound"
        )
        assert np.asarray(series.get_offsets())[:, 1].tolist() == pytest.approx(TWO_ROOT_J[bound])
        assert any(item.get_label() == f"bracket {bound}" for item in ax.collections)
    rings = {
        str(item.get_label()): np.asarray(item.get_offsets())[0]
        for item in ax.collections
        if str(item.get_label()).startswith("K*_")
    }
    # Each root is ringed at the evaluation that closed it, trials 15 and 23.
    assert rings["K*_minimal = 2.564e-05"][0] == pytest.approx(15 - 0.12)
    assert rings["K*_maximal = 1.358e-06"][0] == pytest.approx(23 + 0.12)
    returned = next(item for item in ax.lines if str(item.get_label()).startswith("returned"))
    assert returned.get_xdata()[0] == pytest.approx(24.0)
    note = ax.texts[0].get_text()
    assert "K*_minimal = 2.564e-05, bracket [2.548e-05, 2.564e-05]" in note
    assert "K*_maximal = 1.358e-06, bracket [1.358e-06, 1.366e-06]" in note
    assert "Delta = log10(K*_maximal / K*_minimal) = -1.28 decade(s)" in note
    assert "returned K = 5.9e-06" in note


def test_available_on_a_search_over_two_bounds(tmp_path) -> None:
    # Two bounds publish J_signed_minimal and J_signed_maximal, never J_signed.
    assert BisectionBracketTraceFigure().unavailable_reason(two_root_run(tmp_path)) is None


def test_stage_without_the_diagnostic_is_unavailable(tmp_path) -> None:
    # The second stage of a staged calibration publishes a cost per trial and
    # no network diagnostic. Raising instead cost a converged stage its run.
    rows = [
        {
            "trial": i,
            "parameters": {"Sy": {"value": v}},
            "cost": 0.2 + 0.01 * i,
            "status": "completed",
        }
        for i, v in enumerate((0.05, 0.08), start=1)
    ]
    stage = journal_session(tmp_path, rows, name="storage-stage")

    reason = BisectionBracketTraceFigure().unavailable_reason(stage)

    assert reason is not None
    assert "J_signed" in reason


def test_stage_that_published_the_diagnostic_is_available(tmp_path) -> None:
    run = session_run(
        tmp_path,
        [1e-4, 1e-3],
        [
            {"D_so": 100.0, "D_os": 300.0, "J_signed": -200.0},
            {"D_so": 300.0, "D_os": 100.0, "J_signed": 200.0},
        ],
    )

    assert BisectionBracketTraceFigure().unavailable_reason(run) is None

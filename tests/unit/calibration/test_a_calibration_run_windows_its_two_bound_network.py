"""A calibration run hands its scoring window to a two-bound network output.

The metric function a calibration builds is the route every trial takes. It
must pass the phase's window to the extraction, so the spin-up year leaves
the score, and must not refuse the window on a network output scored by
calendar year. A network output in one state has no year to cut, so a window
on it is still refused.
"""

from __future__ import annotations

import pandas as pd
import pytest

from hydromodpy.calibration.config import CalibObjectiveBlockDecl, validate_calib_output
from hydromodpy.calibration.metrics import solver_extract as _solver_extract
from hydromodpy.calibration.metrics.composite import build_metric_extractor
from tests.unit.calibration.test_the_two_bound_mode_scores_the_years_of_its_window import (
    SPIN_UP_RUN,
    WINDOW,
    _fake_ctx,
    _output,
    _stack,
    _StackAdapter,
    _thresholds,
    bench,  # noqa: F401 (fixture)
    mapped,  # noqa: F401 (fixture)
)

pytest.importorskip("geopandas")

BLOCKS = [
    CalibObjectiveBlockDecl.model_validate(
        {"name": "network", "metric": "distance_gap", "uses_outputs": ["net"]}
    )
]


def _components(monkeypatch, bench, output, window):  # noqa: F811
    ctx = _fake_ctx(bench, SPIN_UP_RUN)
    adapter = _StackAdapter(_stack(bench, _thresholds(3)))
    monkeypatch.setattr(_solver_extract, "resolve_flow_adapter", lambda _ctx: (adapter, ctx))
    metric_fn = build_metric_extractor(
        None, None, ctx, outputs={"net": output}, objective_blocks=BLOCKS, scoring_window=window
    )
    _, components = metric_fn(ctx)
    return components


def test_the_run_scores_only_the_years_of_its_window(monkeypatch, bench, mapped) -> None:  # noqa: F811
    scored = _components(monkeypatch, bench, _output(mapped), WINDOW)
    assert scored["net.n_years_scored"] == 2.0
    assert scored["net.year_scored_y2000"] == 0.0
    assert scored["net.n_years_outside_window"] == 1.0


def test_without_a_window_the_run_scores_every_year(monkeypatch, bench, mapped) -> None:  # noqa: F811
    scored = _components(monkeypatch, bench, _output(mapped), None)
    assert scored["net.n_years_scored"] == 3.0
    assert scored["net.year_scored_y2000"] == 1.0


def test_a_window_on_a_network_in_one_state_is_refused(bench, mapped) -> None:  # noqa: F811
    output = validate_calib_output(
        {
            "support": "network",
            "stream_geometry_path": str(mapped),
            "diagonal_neighbors": True,
            "tau_specific_ratio": 0.0,
        }
    )
    with pytest.raises(ValueError, match=r"cannot be applied to block 'network'"):
        build_metric_extractor(
            None,
            None,
            _fake_ctx(bench, SPIN_UP_RUN),
            outputs={"net": output},
            objective_blocks=BLOCKS,
            scoring_window=(pd.Timestamp("2001-01-01"), None),
        )

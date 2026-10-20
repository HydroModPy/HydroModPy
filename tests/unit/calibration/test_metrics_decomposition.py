"""Smoke tests that lock the metrics sub-package decomposition.

Each sub-module of ``hydromodpy.calibration.metrics`` exposes a focused
concern. These tests import each sub-module independently and exercise one
representative entry point so the package layout stays stable. The network
cost left ``metrics`` for ``observations.network_cost`` and keeps its test here.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def test_observable_scoring_module_exposes_the_block_scorers() -> None:
    from hydromodpy.calibration.metrics import observable_scoring

    assert callable(observable_scoring.ObservableScorer)
    assert callable(observable_scoring.StationBlockScorer)
    assert observable_scoring.sampling_step_days(
        pd.date_range("2020-01-01", periods=3, freq="D")
    ) == pytest.approx(1.0)


def test_series_module_exposes_observed_series_and_helpers() -> None:
    from hydromodpy.calibration.metrics import series

    assert hasattr(series, "ObservedSeries")
    assert callable(series.load_observed)
    assert callable(series.resolve_time_index)
    assert callable(series.add_runoff_to_discharge)


def test_network_cost_module_exposes_network_cost() -> None:
    from hydromodpy.calibration.observations import network_cost

    # Not a 0/1 vector: network_cost refuses a binary mask where a
    # per-cell outflow is required, which is the trap this guards.
    sim = np.array([0.0, 1.0, 0.0, 0.5])
    ref = np.array([0.0, 1.0, 0.0, 0.5])
    centroids = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])
    cell_area = np.ones(4)
    cost = network_cost.network_cost(
        sim,
        ref,
        centroids,
        cell_area,
        d_tol=1.0,
    )
    assert cost.total == pytest.approx(0.0)


def test_composite_module_exposes_build_metric_extractor() -> None:
    from hydromodpy.calibration.metrics import composite

    assert callable(composite.build_metric_extractor)


def test_solver_extract_module_exposes_extractors() -> None:
    from hydromodpy.calibration.metrics import solver_extract

    assert callable(solver_extract.resolve_flow_adapter)
    assert callable(solver_extract.extract_outputs)
    assert callable(solver_extract.observable_request_for_output)
    assert callable(solver_extract.resolve_station_cells)
    assert callable(solver_extract.find_cell_at_point)

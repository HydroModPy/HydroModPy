"""A routed discharge already carries the runoff; adding it again double-counts."""

from __future__ import annotations

import inspect

import numpy as np
import pandas as pd

from hydromodpy.core.contracts.observables import ObservableRequest, ObservableResult
from hydromodpy.solver.base.observables import series_observable


def test_the_flag_defaults_to_false_so_drain_discharge_still_gets_its_runoff():
    result = ObservableResult(request_id="x", values=np.zeros(3), units="m3/s")
    assert result.includes_runoff is False


def test_series_observable_carries_the_flag_through():
    index = pd.date_range("2000-01-01", periods=3, freq="D")
    request = ObservableRequest(id="_catchment", name="discharge", support="domain")
    series = pd.Series([1.0, 2.0, 3.0], index=index)
    assert series_observable(request, series, units="m3/s").includes_runoff is False
    routed = series_observable(request, series, units="m3/s", includes_runoff=True)
    assert routed.includes_runoff is True


def test_the_composite_metric_guards_the_runoff_addition():
    # The guard lives in a branch a unit test cannot reach without a solver run,
    # so assert the source: a refactor that drops it would double-count the
    # runoff on every routed SFR calibration, inflating discharge by ~25 %.
    from hydromodpy.calibration.metrics import composite

    source = inspect.getsource(composite)
    assert "add_runoff_to_discharge(simulated, trial_ctx)" in source
    guard = next(
        line for line in source.splitlines() if "includes_runoff" in line and "if " in line
    )
    assert "not " in guard, (
        "The runoff must be added ONLY when the observable does not already hold it."
    )

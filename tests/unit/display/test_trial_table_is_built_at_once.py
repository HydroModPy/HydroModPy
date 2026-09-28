"""The trial table of a network calibration is built without fragmenting.

A network criterion publishes about a hundred diagnostics per trial. Inserting
them one column at a time fragmented the frame, and pandas printed a
PerformanceWarning on the console of every promoted run.
"""

from __future__ import annotations

import warnings
from types import SimpleNamespace

import pandas as pd

from hydromodpy.display.figures._trial_diagnostics import trial_table


def test_two_hundred_diagnostics_raise_no_performance_warning() -> None:
    metrics = {f"net.diag_{index:03d}": float(index) for index in range(200)}
    rows = [
        {
            "iteration": trial,
            "parameters": {"K": {"value": 10.0 ** -(trial + 4)}},
            "metrics": dict(metrics),
            "objective_value": float(trial),
        }
        for trial in range(5)
    ]
    run = SimpleNamespace(calibration_iterations=pd.DataFrame(rows))

    with warnings.catch_warnings():
        warnings.simplefilter("error", pd.errors.PerformanceWarning)
        table = trial_table(run)

    assert table.parameters == ("K",)
    assert table.frame["net.diag_199"].tolist() == [199.0] * 5
    assert table.frame["K"].tolist()[0] == 1e-4

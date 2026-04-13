from __future__ import annotations

import numpy as np
import pandas as pd

from hydromodpy.analysis.display.flow_payloads import build_flow_cumulative_payload


def test_build_flow_cumulative_payload_converts_si_rates_to_display_mm() -> None:
    timeseries = pd.DataFrame(
        {
            "recharge_budget": [1.0e-3 / 86_400.0, 1.0e-3 / 86_400.0],
            "outflow_drain": [0.5e-3 / 86_400.0, 0.5e-3 / 86_400.0],
            "runoff": [0.25e-3 / 86_400.0, 0.25e-3 / 86_400.0],
        },
        index=pd.to_datetime(["2000-01-01", "2000-01-11"]),
    )

    payload = build_flow_cumulative_payload(timeseries, run_id="flow")

    assert payload is not None
    assert np.allclose(payload.time_days, [0.0, 10.0])
    assert np.allclose(payload.recharge_cumulative_mm, [10.0, 20.0])
    assert payload.discharge_components_cumulative_mm is not None
    assert np.allclose(
        payload.discharge_components_cumulative_mm["Drain discharge"],
        [5.0, 10.0],
    )
    assert np.allclose(
        payload.discharge_components_cumulative_mm["Runoff"],
        [2.5, 5.0],
    )
    assert np.allclose(payload.discharge_total_cumulative_mm, [7.5, 15.0])


def test_build_flow_cumulative_payload_ignores_empty_optional_components() -> None:
    timeseries = pd.DataFrame(
        {
            "recharge_budget": [2.0e-3 / 86_400.0, 0.0],
            "outflow_drain": [1.0e-3 / 86_400.0, 1.0e-3 / 86_400.0],
            "runoff": [np.nan, np.nan],
        },
        index=pd.to_datetime(["2000-01-01", "2000-01-11"]),
    )

    payload = build_flow_cumulative_payload(timeseries, run_id="flow")

    assert payload is not None
    assert payload.discharge_components_cumulative_mm is not None
    assert "Runoff" not in payload.discharge_components_cumulative_mm
    assert np.allclose(payload.recharge_cumulative_mm, [20.0, 20.0])
    assert np.allclose(payload.discharge_total_cumulative_mm, [10.0, 20.0])

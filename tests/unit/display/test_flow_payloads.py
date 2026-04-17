from __future__ import annotations

import numpy as np
import pandas as pd
import warnings

from hydromodpy.analysis.display.flow_payloads import (
    FlowCumulativeSeriesPayload,
    FlowSpatialFigurePayload,
    build_flow_cumulative_payload,
)
from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh


def test_build_flow_cumulative_payload_converts_si_rates_to_display_mm() -> None:
    timeseries = pd.DataFrame(
        {
            "recharge": [1.0e-3 / 86_400.0, 1.0e-3 / 86_400.0],
            "outflow_drain": [0.5e-3 / 86_400.0, 0.5e-3 / 86_400.0],
            "runoff": [0.25e-3 / 86_400.0, 0.25e-3 / 86_400.0],
        },
        index=pd.to_datetime(["2000-01-01", "2000-01-11"]),
    )

    payload = build_flow_cumulative_payload(timeseries, artifact_id="flow")

    assert payload is not None
    assert payload.artifact_id == "flow"
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", DeprecationWarning)
        legacy_run_id = payload.run_id
    assert legacy_run_id == "flow"
    assert len(caught) == 1
    assert "deprecated" in str(caught[0].message)
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
            "recharge": [2.0e-3 / 86_400.0, 0.0],
            "outflow_drain": [1.0e-3 / 86_400.0, 1.0e-3 / 86_400.0],
            "runoff": [np.nan, np.nan],
        },
        index=pd.to_datetime(["2000-01-01", "2000-01-11"]),
    )

    payload = build_flow_cumulative_payload(timeseries, artifact_id="flow")

    assert payload is not None
    assert payload.discharge_components_cumulative_mm is not None
    assert "Runoff" not in payload.discharge_components_cumulative_mm
    assert np.allclose(payload.recharge_cumulative_mm, [20.0, 20.0])
    assert np.allclose(payload.discharge_total_cumulative_mm, [10.0, 20.0])


def test_build_flow_cumulative_payload_rejects_missing_identifier() -> None:
    timeseries = pd.DataFrame({"recharge": [0.0]}, index=pd.to_datetime(["2000-01-01"]))

    try:
        build_flow_cumulative_payload(timeseries)
    except TypeError as exc:
        assert "artifact_id" in str(exc)
    else:
        raise AssertionError("build_flow_cumulative_payload should require an identifier")


def test_build_flow_cumulative_payload_accepts_legacy_run_id_with_deprecation() -> None:
    timeseries = pd.DataFrame({"recharge": [0.0]}, index=pd.to_datetime(["2000-01-01"]))

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", DeprecationWarning)
        payload = build_flow_cumulative_payload(timeseries, run_id="legacy_flow")

    assert payload is not None
    assert payload.artifact_id == "legacy_flow"
    assert len(caught) == 1
    assert "deprecated" in str(caught[0].message)


def test_flow_payload_constructors_accept_legacy_run_id_with_deprecation() -> None:
    hydro_mesh = HydroMesh(
        vertices=np.asarray(
            [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]],
            dtype=float,
        ),
        cell_blocks=(
            CellBlock(
                cell_type=CellType.TRIANGLE,
                connectivity=np.asarray([[0, 1, 2]], dtype=int),
            ),
        ),
    )

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", DeprecationWarning)
        spatial_payload = FlowSpatialFigurePayload(run_id="legacy_flow", hydro_mesh=hydro_mesh)
        cumulative_payload = FlowCumulativeSeriesPayload(
            run_id="legacy_flow",
            time_days=np.asarray([0.0], dtype=float),
        )

    assert spatial_payload.artifact_id == "legacy_flow"
    assert cumulative_payload.artifact_id == "legacy_flow"
    assert len(caught) == 2

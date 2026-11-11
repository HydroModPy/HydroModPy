from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.model.boundaries.climate import (
    apply_etp_load_result_to_flow,
    apply_oceanic_to_flow,
    apply_recharge_load_result_to_flow,
)
from hydromodpy.model.forcing.forcing_bridge import (
    ResolvedForcing,
    build_forcing_series,
    extract_homogeneous_series,
    resolve_forcing,
)
from hydromodpy.model.sinks_sources.etp import FlowEtpConfig
from hydromodpy.model.time.history_contract import (
    build_transient_time_axes,
    step_history_from_history,
)


class _LoadResult:
    def __init__(self, *, points: list[object] | None = None, fields: list[object] | None = None):
        self.points = points or []
        self.fields = fields or []

    @property
    def has_points(self) -> bool:
        return bool(self.points)

    @property
    def has_fields(self) -> bool:
        return bool(self.fields)


def _point(values: list[float], *, x: float | None = None, y: float | None = None) -> object:
    location = None if x is None or y is None else SimpleNamespace(x=x, y=y)
    return SimpleNamespace(
        data=pd.DataFrame(
            {
                "datetime": pd.to_datetime(["2020-01-02", "2020-01-01"][: len(values)]),
                "value": values,
            }
        ),
        location=location,
    )


def test_history_contract_aligns_snapshots_and_step_histories() -> None:
    axes = build_transient_time_axes([10.0, 20.0, 30.0])

    assert axes.n_steps == 3
    assert axes.snapshot_elapsed_seconds.tolist() == [0.0, 10.0, 30.0, 60.0]
    assert step_history_from_history(
        np.asarray([1.0, 2.0, 3.0, 4.0]), n_steps=3, name="h"
    ).tolist() == [
        2.0,
        3.0,
        4.0,
    ]
    np.testing.assert_allclose(
        step_history_from_history(np.asarray([[1.0, 2.0], [3.0, 4.0]]), n_steps=2, name="h"),
        np.asarray([[1.0, 2.0], [3.0, 4.0]]),
    )

    with pytest.raises(ValueError, match="expected 3 step rows"):
        step_history_from_history(np.zeros((2, 2)), n_steps=3, name="h")


def test_forcing_bridge_averages_station_series_and_dispatches_spatial_modes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    point_a = _point([2.0, 4.0])
    point_b = _point([6.0, 8.0])
    result = _LoadResult(points=[point_a, point_b], fields=[object()])

    series = extract_homogeneous_series(result)
    resolved_auto = resolve_forcing(result, unit_conversion_factor=0.5, spatial_mode="auto")

    assert series is not None
    assert series.index.tolist() == pd.to_datetime(["2020-01-01", "2020-01-02"]).tolist()
    assert series.tolist() == [6.0, 4.0]
    assert resolved_auto is not None
    assert resolved_auto.series is not None
    assert resolved_auto.series.tolist() == [3.0, 2.0]
    assert resolved_auto.heterogeneous_source is result

    field_result = _LoadResult(fields=[object()])
    monkeypatch.setattr(
        "hydromodpy.model.forcing.forcing_bridge.spatial_mean_from_fields",
        lambda _result: pd.Series([10.0], index=pd.to_datetime(["2020-01-01"])),
    )
    assert build_forcing_series(field_result, force_homogeneous=True).tolist() == [10.0]
    assert resolve_forcing(field_result, spatial_mode="homogeneous") is not None
    assert resolve_forcing(_LoadResult(), spatial_mode="auto") is None


def test_forcing_bridge_can_use_located_points_as_heterogeneous_source() -> None:
    located_without_values = SimpleNamespace(
        data=pd.DataFrame(columns=["datetime", "value"]),
        location=SimpleNamespace(x=1.0, y=2.0),
    )
    result = _LoadResult(points=[located_without_values])

    resolved = resolve_forcing(result, spatial_mode="heterogeneous", interpolation_method="idw")

    assert resolved is not None
    assert resolved.series is None
    assert resolved.heterogeneous_source is result
    assert resolved.interpolation_method == "idw"


def test_oceanic_binder_prefers_constant_msl_then_tide_gauge_mean() -> None:
    ocean = SimpleNamespace(value=None)
    flow = SimpleNamespace(boundary_conditions={"ocean": ocean}, active_bc=["ocean"])
    constant = SimpleNamespace(
        variable="mean_sea_level",
        is_constant=True,
        data=pd.DataFrame({"value": [2.5]}),
    )

    apply_oceanic_to_flow(flow=flow, oceanic=SimpleNamespace(points=[constant]))

    assert ocean.value == pytest.approx(2.5)

    ocean.value = None
    tide = SimpleNamespace(
        variable="sea_level",
        is_constant=False,
        data=pd.DataFrame({"value": [1.0, 3.0]}),
    )
    apply_oceanic_to_flow(flow=flow, oceanic=SimpleNamespace(points=[tide]))

    assert ocean.value == pytest.approx(2.0)


def test_recharge_binder_preserves_existing_policy_and_solver_units(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    source = _LoadResult(points=[_point([1.0])])
    resolved = ResolvedForcing(
        series=pd.Series([1.2e-8], index=pd.to_datetime(["2020-01-01"])),
        heterogeneous_source=source,
        spatial_mode="heterogeneous",
        interpolation_method="linear",
    )

    def fake_resolve_forcing(*args: object, **kwargs: object) -> ResolvedForcing:
        captured["args"] = args
        captured.update(kwargs)
        return resolved

    monkeypatch.setattr(
        "hydromodpy.model.forcing.forcing_bridge.resolve_forcing",
        fake_resolve_forcing,
    )
    flow = SimpleNamespace(
        sinks_sources={
            "recharge": SimpleNamespace(
                first_clim="first",
                spatial_mode="heterogeneous",
                interpolation_method="linear",
                negative_to_evt=False,
            )
        },
        set_recharge=lambda cfg: setattr(flow, "bound_recharge", cfg),
    )

    assert apply_recharge_load_result_to_flow(flow=flow, recharge_result=source)

    assert captured["spatial_mode"] == "heterogeneous"
    assert captured["interpolation_method"] == "linear"
    assert captured["unit_conversion_factor"] < 1.0
    assert flow.bound_recharge.units == "m/s"
    assert flow.bound_recharge.first_clim == "first"
    assert flow.bound_recharge.negative_to_evt is False
    assert flow.bound_recharge.heterogeneous_source is source


def test_etp_binder_preserves_surface_depth_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    source = _LoadResult(points=[_point([1.0])])
    resolved = ResolvedForcing(
        series=pd.Series([2.0e-8], index=pd.to_datetime(["2020-01-01"])),
        heterogeneous_source=None,
        spatial_mode="homogeneous",
        interpolation_method="idw",
    )
    monkeypatch.setattr(
        "hydromodpy.model.forcing.forcing_bridge.resolve_forcing",
        lambda *args, **kwargs: resolved,
    )
    flow = SimpleNamespace(
        sinks_sources={
            "etp": FlowEtpConfig(
                first_clim="first",
                spatial_mode="homogeneous",
                interpolation_method="idw",
                surface_offset=3.0,
                extinction_depth=4.0,
            )
        },
        set_etp=lambda cfg: setattr(flow, "bound_etp", cfg),
    )

    assert apply_etp_load_result_to_flow(flow=flow, etp_result=source)

    assert flow.bound_etp.units == "m/s"
    assert flow.bound_etp.first_clim == "first"
    assert flow.bound_etp.spatial_mode == "homogeneous"
    assert float(flow.bound_etp.surface_offset.to("m").magnitude) == pytest.approx(3.0)
    assert float(flow.bound_etp.extinction_depth) == pytest.approx(4.0)

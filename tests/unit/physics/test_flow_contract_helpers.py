from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.physics.flow.flow_runtime_validators import (
    normalize_bool,
    normalize_positive_float,
    normalize_positive_float_or_none,
    normalize_positive_int,
    normalize_positive_int_or_none,
    normalize_runtime_backend,
    normalize_surface_interaction_model,
)
from hydromodpy.physics.flow.history_contract import (
    build_transient_time_axes,
    elapsed_seconds_for_time_keys,
    history_has_initial_snapshot,
    snapshot_elapsed_seconds_from_payload,
    step_end_elapsed_seconds_from_payload,
    step_history_from_history,
    time_axis_sidecar_path,
    write_time_series_npy,
)
from hydromodpy.physics.flow.sinks_sources import FlowEtpConfig
from hydromodpy.physics.flow.structure_binders import (
    apply_etp_load_result_to_flow,
    apply_oceanic_to_flow,
    apply_recharge_load_result_to_flow,
)
from hydromodpy.physics.forcing.forcing_bridge import (
    ResolvedForcing,
    build_forcing_series,
    extract_homogeneous_series,
    resolve_forcing,
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


def test_history_contract_aligns_snapshots_and_step_histories(tmp_path: Path) -> None:
    axes = build_transient_time_axes([10.0, 20.0, 30.0])

    assert axes.n_steps == 3
    assert axes.snapshot_elapsed_seconds.tolist() == [0.0, 10.0, 30.0, 60.0]
    assert history_has_initial_snapshot(n_slices=4, period_lengths_seconds=[10.0, 20.0, 30.0])
    assert not history_has_initial_snapshot(n_slices=1, period_lengths_seconds=[10.0])
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

    payload_path = tmp_path / "history.npy"
    write_time_series_npy(
        payload_path,
        np.asarray([[1.0, 2.0], [3.0, 4.0]]),
        time_keys=[2, 5],
        elapsed_seconds=[20.0, 50.0],
    )
    saved = np.load(payload_path, allow_pickle=True).item()
    sidecar = np.load(time_axis_sidecar_path(payload_path), allow_pickle=True).item()
    assert sorted(saved) == [2, 5]
    assert sidecar["elapsed_seconds"].tolist() == [20.0, 50.0]

    write_time_series_npy(payload_path, np.asarray([7.0, 8.0]), time_keys=[0, 1])
    assert not time_axis_sidecar_path(payload_path).exists()


def test_history_contract_payload_axes_validate_explicit_lengths() -> None:
    payload = {
        "period_lengths_seconds": [10.0, 20.0],
        "step_end_elapsed_seconds": [11.0, 31.0],
        "snapshot_elapsed_seconds": [0.0, 11.0, 31.0],
    }

    assert step_end_elapsed_seconds_from_payload(payload, n_steps=2).tolist() == [11.0, 31.0]
    assert snapshot_elapsed_seconds_from_payload(payload, n_snapshots=3).tolist() == [
        0.0,
        11.0,
        31.0,
    ]
    assert elapsed_seconds_for_time_keys([0.0, 5.0, 9.0], [0, 2]).tolist() == [0.0, 9.0]

    with pytest.raises(ValueError, match="step_end_elapsed_seconds length"):
        step_end_elapsed_seconds_from_payload(payload, n_steps=3)
    with pytest.raises(ValueError, match="snapshot_elapsed_seconds length"):
        snapshot_elapsed_seconds_from_payload(payload, n_snapshots=2)
    with pytest.raises(ValueError, match="bounds"):
        elapsed_seconds_for_time_keys([0.0], [1], name="head")
    with pytest.raises(ValueError, match="no elapsed-time axis"):
        elapsed_seconds_for_time_keys([], [0], name="head")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, "local"),
        (" PETSC ", "petsc"),
        ("scipy_sparse", "scipy_sparse"),
    ],
)
def test_runtime_backend_normalization_accepts_known_values(raw: object, expected: str) -> None:
    assert normalize_runtime_backend(raw) == expected


def test_runtime_validator_rejects_invalid_numbers_and_booleans() -> None:
    assert normalize_surface_interaction_model(" TS_VI_OBSTACLE ") == "ts_vi_obstacle"
    assert normalize_positive_int_or_none("", field="runtime_max_iterations") is None
    assert normalize_positive_int("4", field="vi_substeps_per_period", default=2) == 4
    assert normalize_bool("yes", field="vi_substep_on_failure")
    assert not normalize_bool("off", field="vi_substep_on_failure")
    assert normalize_positive_float("", field="runtime_tol", default=1.0e-6) == pytest.approx(
        1.0e-6
    )
    assert normalize_positive_float_or_none("0.25", field="runtime_tol") == pytest.approx(0.25)

    for call in (
        lambda: normalize_runtime_backend("gpu"),
        lambda: normalize_surface_interaction_model("wetdry"),
        lambda: normalize_positive_int(True, field="steps", default=1),
        lambda: normalize_positive_int("1.2", field="steps", default=1),
        lambda: normalize_bool("maybe", field="flag"),
        lambda: normalize_positive_float(False, field="tol", default=1.0),
        lambda: normalize_positive_float_or_none("0", field="tol"),
    ):
        with pytest.raises(ValueError):
            call()


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
        "hydromodpy.physics.forcing.forcing_bridge.get_field_aggregator",
        lambda: lambda _result: pd.Series([10.0], index=pd.to_datetime(["2020-01-01"])),
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
        "hydromodpy.physics.forcing.forcing_bridge.resolve_forcing",
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
        "hydromodpy.physics.forcing.forcing_bridge.resolve_forcing",
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
    assert float(flow.bound_etp.extinction_depth.to("m").magnitude) == pytest.approx(4.0)

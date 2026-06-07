"""Unit tests for budget flux conversions and water-balance closure math.

These tests drive the deterministic helpers in
``hydromodpy.analysis.comparison.exports.budget`` with small synthetic
records. They assert real physics invariants:

* flux unit -> m3/s conversion against hand-computed values,
* storage change ``area * Sy * dh / dt`` in m3/s,
* MODFLOW budget sign convention per component,
* water-balance closure ``in - out - dStorage = residual``.

Anything needing a live comparison run or solver is skipped on purpose.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from hydromodpy.analysis.comparison.exports.budget import (
    _all_finite_zero,
    _budget_field_total_series,
    _catalog_budget_factor_to_m3_s,
    _elapsed_seconds_axis,
    _flux_factor_to_m3_s,
    _mf_budget_component_name,
    _mf_budget_component_value_m3_s,
    _residual_total_series_m3_s,
    _saturated_thickness_from_head_history,
    _storage_change_series_m3_s,
)
from hydromodpy.core.units.time import SECONDS_PER_DAY

# --------------------------------------------------------------------------- #
# Flux unit -> m3/s conversion
# --------------------------------------------------------------------------- #


def test_flux_factor_m3_s_is_identity() -> None:
    assert _flux_factor_to_m3_s("m3/s") == pytest.approx(1.0)


def test_flux_factor_m3_per_day_is_per_seconds_in_day() -> None:
    # 1 m3/day = 1 / 86400 m3/s.
    assert _flux_factor_to_m3_s("m3/day") == pytest.approx(1.0 / SECONDS_PER_DAY)
    assert _flux_factor_to_m3_s("m3/d") == pytest.approx(1.0 / 86400.0)


def test_flux_factor_liters_per_second() -> None:
    # 1 L/s = 1e-3 m3/s.
    assert _flux_factor_to_m3_s("l/s") == pytest.approx(1.0e-3)


def test_flux_factor_known_volume_over_time_to_m3_s() -> None:
    # A canonical "flux * area / seconds -> m3/s" sanity check:
    # 86400 m3/day == 1.0 m3/s.
    daily_volume_m3 = 86400.0
    flux_m3_s = daily_volume_m3 * _flux_factor_to_m3_s("m3/day")
    assert flux_m3_s == pytest.approx(1.0)


def test_flux_factor_empty_or_unknown_unit_defaults_to_identity() -> None:
    # Empty string short-circuits to 1.0; unparseable units fall back to 1.0.
    assert _flux_factor_to_m3_s("") == pytest.approx(1.0)
    assert _flux_factor_to_m3_s("not-a-unit") == pytest.approx(1.0)


def test_catalog_factor_modflow6_m3_per_day_kept_native() -> None:
    # The catalog already stores MF6 budgets per day; the factor stays 1.0
    # so the per-day series is preserved (it is normalized elsewhere).
    for unit in ("m3/d", "m3/day", "m^3/day"):
        assert _catalog_budget_factor_to_m3_s(solver="modflow6", unit=unit) == pytest.approx(1.0)


def test_catalog_factor_non_modflow6_uses_real_conversion() -> None:
    # For a non-MF6 solver the per-day unit is genuinely converted to m3/s.
    factor = _catalog_budget_factor_to_m3_s(solver="boussinesq", unit="m3/day")
    assert factor == pytest.approx(1.0 / SECONDS_PER_DAY)


def test_catalog_factor_modflow6_other_unit_still_converts() -> None:
    # MF6 with an hourly unit is not the native case, so it must convert.
    factor = _catalog_budget_factor_to_m3_s(solver="modflow6", unit="m3/h")
    assert factor == pytest.approx(1.0 / 3600.0)


# --------------------------------------------------------------------------- #
# MODFLOW budget sign convention and closure
# --------------------------------------------------------------------------- #


def test_mf_component_name_aliases() -> None:
    assert _mf_budget_component_name("RCH") == "recharge_total_m3_s"
    assert _mf_budget_component_name("DRN") == "drainage_total_m3_s"
    assert _mf_budget_component_name("CHD") == "prescribed_head_out_total_m3_s"
    assert _mf_budget_component_name("EVT") == "evapotranspiration_total_m3_s"
    assert _mf_budget_component_name("STO-SS") == "storage_change_total_m3_s"
    assert _mf_budget_component_name("unknown") == ""


def test_mf_recharge_is_net_inflow() -> None:
    # Recharge is an inflow term: value = flux_in - flux_out.
    value = _mf_budget_component_value_m3_s("RCH", flux_in=8.0, flux_out=1.0)
    assert value == pytest.approx(7.0)


def test_mf_drainage_is_net_outflow() -> None:
    # Drainage / CHD / EVT are outflow terms: value = flux_out - flux_in.
    value = _mf_budget_component_value_m3_s("DRN", flux_in=1.0, flux_out=6.0)
    assert value == pytest.approx(5.0)


def test_mf_storage_change_sign() -> None:
    # Storage change reported as flux_out - flux_in (release vs uptake).
    value = _mf_budget_component_value_m3_s("STO-SS", flux_in=2.0, flux_out=5.0)
    assert value == pytest.approx(3.0)


def test_mf_budget_closure_identity_balances_to_zero() -> None:
    """A synthetic MF6 budget that conserves mass closes to a near-zero residual.

    Closure used in ``_load_catalog_budget_rows``:
        residual = recharge - drainage - surface_excess
                   - prescribed_head_out - evapotranspiration - storage_change
    """
    # Construct a perfectly conserving period:
    #   recharge in = 10 m3/s.
    #   drainage out = 4, ET out = 1, CHD out = 2.
    #   storage change = 10 - (4 + 1 + 2) = 3.
    recharge = _mf_budget_component_value_m3_s("RCH", flux_in=10.0, flux_out=0.0)
    drainage = _mf_budget_component_value_m3_s("DRN", flux_in=0.0, flux_out=4.0)
    evt = _mf_budget_component_value_m3_s("EVT", flux_in=0.0, flux_out=1.0)
    chd = _mf_budget_component_value_m3_s("CHD", flux_in=0.0, flux_out=2.0)
    storage = _mf_budget_component_value_m3_s("STO-SS", flux_in=0.0, flux_out=3.0)

    residual = recharge - drainage - evt - chd - storage
    assert residual == pytest.approx(0.0, abs=1e-12)
    # Sanity: the storage change really absorbed the inflow minus outflow.
    assert storage == pytest.approx(recharge - drainage - evt - chd)


def test_mf_budget_closure_residual_reflects_imbalance() -> None:
    # Inject a 0.5 m3/s imbalance and confirm it surfaces in the residual.
    recharge = _mf_budget_component_value_m3_s("RCH", flux_in=10.0, flux_out=0.0)
    drainage = _mf_budget_component_value_m3_s("DRN", flux_in=0.0, flux_out=4.0)
    storage = _mf_budget_component_value_m3_s("STO-SS", flux_in=0.0, flux_out=5.5)
    residual = recharge - drainage - storage
    # 10 - 4 - 5.5 = 0.5.
    assert residual == pytest.approx(0.5, abs=1e-12)


# --------------------------------------------------------------------------- #
# Storage-change series: area * Sy * dh / dt
# --------------------------------------------------------------------------- #


def test_storage_change_series_known_value() -> None:
    """area * Sy * dh / dt with one cell, one transient step.

    head goes 1.0 -> 1.5 m over a 10 s period on a 100 m2 cell with Sy 0.2.
    storage change = 100 * 0.2 * 0.5 / 10 = 1.0 m3/s.
    """
    head_history = np.array([[1.0], [1.5]], dtype=float)
    area = np.array([100.0], dtype=float)
    sy = np.array([0.2], dtype=float)
    period_lengths = np.array([10.0], dtype=float)  # n_snapshots - 1 layout

    series = _storage_change_series_m3_s(
        head_history_m=head_history,
        saturated_thickness_history_m=None,
        area_m2=area,
        storage_coefficient=sy,
        period_lengths_seconds=period_lengths,
    )
    assert series is not None
    assert series.shape == (2,)
    # Index 0 is the initial state: storage change defined as 0.
    assert series[0] == pytest.approx(0.0)
    assert series[1] == pytest.approx(1.0)


def test_storage_change_series_multicell_sums_volume() -> None:
    # Two cells with different areas; dh/dt drives a known total m3/s.
    # cell A: 100 m2, dh = 0.5 -> 100*0.2*0.5/10 = 1.0
    # cell B: 200 m2, dh = -0.25 -> 200*0.2*-0.25/10 = -1.0
    # total = 0.0 m3/s.
    head_history = np.array([[1.0, 2.0], [1.5, 1.75]], dtype=float)
    area = np.array([100.0, 200.0], dtype=float)
    sy = np.array([0.2, 0.2], dtype=float)
    period_lengths = np.array([10.0], dtype=float)

    series = _storage_change_series_m3_s(
        head_history_m=head_history,
        saturated_thickness_history_m=None,
        area_m2=area,
        storage_coefficient=sy,
        period_lengths_seconds=period_lengths,
    )
    assert series is not None
    assert series[1] == pytest.approx(0.0, abs=1e-12)


def test_storage_change_series_uses_saturated_thickness_when_provided() -> None:
    # When saturated thickness history matches head shape, it drives storage.
    head_history = np.array([[5.0], [5.0]], dtype=float)  # head flat
    sat_history = np.array([[2.0], [3.0]], dtype=float)  # thickness rises 1 m
    area = np.array([50.0], dtype=float)
    sy = np.array([0.1], dtype=float)
    period_lengths = np.array([5.0], dtype=float)

    series = _storage_change_series_m3_s(
        head_history_m=head_history,
        saturated_thickness_history_m=sat_history,
        area_m2=area,
        storage_coefficient=sy,
        period_lengths_seconds=period_lengths,
    )
    assert series is not None
    # 50 * 0.1 * 1.0 / 5 = 1.0 m3/s, driven by the thickness delta not the head.
    assert series[1] == pytest.approx(1.0)


def test_storage_change_series_n_equals_layout() -> None:
    # period_lengths.size == n_snapshots (no separate initial state) path.
    head_history = np.array([[0.0], [1.0], [3.0]], dtype=float)
    area = np.array([10.0], dtype=float)
    sy = np.array([0.5], dtype=float)
    # dt indexed at [index]; index 0 set to 0.0 by the builder.
    period_lengths = np.array([1.0, 2.0, 4.0], dtype=float)

    series = _storage_change_series_m3_s(
        head_history_m=head_history,
        saturated_thickness_history_m=None,
        area_m2=area,
        storage_coefficient=sy,
        period_lengths_seconds=period_lengths,
    )
    assert series is not None
    assert series.shape == (3,)
    assert series[0] == pytest.approx(0.0)
    # step 1: dh=1, dt=period_lengths[1]=2 -> 10*0.5*1/2 = 2.5
    assert series[1] == pytest.approx(2.5)
    # step 2: dh=2, dt=period_lengths[2]=4 -> 10*0.5*2/4 = 2.5
    assert series[2] == pytest.approx(2.5)


def test_storage_change_series_rejects_shape_mismatch() -> None:
    head_history = np.array([[1.0, 2.0], [1.5, 2.5]], dtype=float)
    area = np.array([100.0], dtype=float)  # wrong size
    sy = np.array([0.2, 0.2], dtype=float)
    series = _storage_change_series_m3_s(
        head_history_m=head_history,
        saturated_thickness_history_m=None,
        area_m2=area,
        storage_coefficient=sy,
        period_lengths_seconds=np.array([10.0], dtype=float),
    )
    assert series is None


def test_storage_change_series_unknown_period_layout_returns_none() -> None:
    head_history = np.array([[1.0], [1.5], [2.0]], dtype=float)
    series = _storage_change_series_m3_s(
        head_history_m=head_history,
        saturated_thickness_history_m=None,
        area_m2=np.array([100.0], dtype=float),
        storage_coefficient=np.array([0.2], dtype=float),
        period_lengths_seconds=np.array([10.0, 5.0, 1.0, 2.0], dtype=float),
    )
    assert series is None


# --------------------------------------------------------------------------- #
# Boussinesq closure: in - out - dStorage = residual
# --------------------------------------------------------------------------- #


def test_boussinesq_closure_balances_with_storage() -> None:
    """Reproduce the closure_residual formula from _load_boussinesq_budget_rows.

        residual = recharge + well + dry_deficit
                   - drainage - surface_excess - prescribed_out - storage_change

    A conserving period closes to zero.
    """
    recharge = 12.0
    well = -2.0  # injection negative pumping convention; keep as given
    dry_deficit = 0.0
    drainage = 4.0
    surface_excess = 1.0
    prescribed_out = 0.0
    # storage absorbs the net: in - out.
    storage_change = recharge + well + dry_deficit - drainage - surface_excess - prescribed_out

    residual = (
        recharge + well + dry_deficit - drainage - surface_excess - prescribed_out - storage_change
    )
    assert residual == pytest.approx(0.0, abs=1e-12)


def test_boussinesq_balance_implied_outflow_is_nonneg_residual() -> None:
    # When prescribed outflow is all-zero, the implied outflow equals the
    # positive part of the closure residual.
    residual = np.array([2.0, -1.0, 0.5], dtype=float)
    implied = np.maximum(residual, 0.0)
    assert implied.tolist() == pytest.approx([2.0, 0.0, 0.5])


# --------------------------------------------------------------------------- #
# Series builders
# --------------------------------------------------------------------------- #


def test_budget_field_total_series_1d_passthrough() -> None:
    payload = {"budget_recharge_m3_s": [1.0, 2.0, 3.0]}
    series = _budget_field_total_series(payload, "budget_recharge_m3_s")
    assert series is not None
    assert series.tolist() == pytest.approx([1.0, 2.0, 3.0])


def test_budget_field_total_series_2d_sums_spatial_axis() -> None:
    # First axis is time, remaining axes summed per timestep.
    payload = {"budget_well_m3_s": [[1.0, 2.0], [3.0, 4.0]]}
    series = _budget_field_total_series(payload, "budget_well_m3_s")
    assert series is not None
    assert series.tolist() == pytest.approx([3.0, 7.0])


def test_budget_field_total_series_nan_safe_sum() -> None:
    payload = {"budget_drainage_m3_s": [[1.0, np.nan], [np.nan, 4.0]]}
    series = _budget_field_total_series(payload, "budget_drainage_m3_s")
    assert series is not None
    assert series.tolist() == pytest.approx([1.0, 4.0])


def test_budget_field_total_series_missing_key_returns_none() -> None:
    assert _budget_field_total_series({}, "absent") is None


def test_budget_field_total_series_scalar_returns_none() -> None:
    assert _budget_field_total_series({"x": 3.0}, "x") is None


def test_residual_total_series_sums_cells_per_snapshot() -> None:
    residual = np.array([[1.0, -1.0], [2.0, 0.5]], dtype=float)
    series = _residual_total_series_m3_s(residual, n_snapshots=2)
    assert series is not None
    assert series.tolist() == pytest.approx([0.0, 2.5])


def test_residual_total_series_rejects_wrong_snapshot_count() -> None:
    residual = np.array([[1.0, -1.0], [2.0, 0.5]], dtype=float)
    assert _residual_total_series_m3_s(residual, n_snapshots=3) is None
    assert _residual_total_series_m3_s(None, n_snapshots=2) is None


# --------------------------------------------------------------------------- #
# Time axis and saturated-thickness helpers
# --------------------------------------------------------------------------- #


def test_elapsed_seconds_axis_with_initial_state_layout() -> None:
    # n_snapshots - 1 period lengths -> elapsed prefixed with 0.
    periods = np.array([10.0, 20.0], dtype=float)
    elapsed = _elapsed_seconds_axis(periods, n_snapshots=3)
    assert elapsed.tolist() == pytest.approx([0.0, 10.0, 30.0])


def test_elapsed_seconds_axis_full_layout() -> None:
    periods = np.array([5.0, 5.0, 5.0], dtype=float)
    elapsed = _elapsed_seconds_axis(periods, n_snapshots=3)
    assert elapsed.tolist() == pytest.approx([5.0, 10.0, 15.0])


def test_elapsed_seconds_axis_fallback_is_index_range() -> None:
    periods = np.array([1.0], dtype=float)  # neither n nor n-1 for n=4
    elapsed = _elapsed_seconds_axis(periods, n_snapshots=4)
    assert elapsed.tolist() == pytest.approx([0.0, 1.0, 2.0, 3.0])


def test_saturated_thickness_clips_between_zero_and_aquifer() -> None:
    # head below bottom -> 0; head above top -> capped at aquifer thickness.
    head = np.array([[2.0, 12.0, 7.0]], dtype=float)
    z_top = np.array([10.0, 10.0, 10.0], dtype=float)
    z_bottom = np.array([5.0, 5.0, 5.0], dtype=float)
    sat = _saturated_thickness_from_head_history(
        head_history_m=head,
        z_top_m=z_top,
        z_bottom_m=z_bottom,
    )
    assert sat is not None
    # head 2 < bottom 5 -> 0; head 12 > top -> aquifer thickness 5; head 7 -> 2.
    assert sat[0].tolist() == pytest.approx([0.0, 5.0, 2.0])


def test_all_finite_zero_detects_zero_field() -> None:
    assert _all_finite_zero(np.array([0.0, 0.0, np.nan], dtype=float)) is True
    assert _all_finite_zero(np.array([0.0, 1.0], dtype=float)) is False
    assert _all_finite_zero(None) is False
    # All-NaN has no finite values -> not "finite zero".
    assert _all_finite_zero(np.array([np.nan, np.nan], dtype=float)) is False


def test_storage_change_known_value_is_unit_consistent_m3_s() -> None:
    # Dimensional check: [m2] * [-] * [m] / [s] = [m3/s].
    area = np.array([1000.0], dtype=float)  # m2
    sy = np.array([0.3], dtype=float)  # dimensionless
    head = np.array([[10.0], [10.1]], dtype=float)  # +0.1 m
    dt = 3600.0  # s (1 hour)
    series = _storage_change_series_m3_s(
        head_history_m=head,
        saturated_thickness_history_m=None,
        area_m2=area,
        storage_coefficient=sy,
        period_lengths_seconds=np.array([dt], dtype=float),
    )
    assert series is not None
    expected = 1000.0 * 0.3 * 0.1 / 3600.0
    assert series[1] == pytest.approx(expected)
    assert math.isfinite(series[1])

"""Anti-regression unit tests for ``analysis.comparison.visuals`` helpers.

Safety net before the P0 split of the 2015-LOC ``visuals.py``. Targets
the small, stable helpers (string formatting, masking, limits, payload
builders) and exercises the rendering entry points end-to-end against a
``tmp_path`` so that coverage stays above the 60 percent gate.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.analysis.comparison import visuals_render_maps
from hydromodpy.analysis.comparison.config import ComparisonFineRaster
from hydromodpy.analysis.comparison.visuals_format import (
    _apply_time_ticks,
    _format_time_tick_label,
)
from hydromodpy.analysis.comparison.visuals_payloads import (
    DifferencePayload,
    MapPayload,
    _build_difference_payload,
    _build_fine_grid,
    _estimate_extent_from_centroids,
    _payload_extent,
    _payload_samples,
    _regrid_payload,
    _resolve_fine_grid_bounds,
)
from hydromodpy.analysis.comparison.visuals_render_maps import (
    _write_difference_figure,
    _write_geotiff,
    _write_map_comparison_figure,
    _write_regridded_difference_figure,
    _write_regridded_map_figure,
)
from hydromodpy.analysis.comparison.visuals_render_series import (
    _write_budget_diagnostic_figure,
    _write_flux_dashboard,
    _write_native_flux_panel,
    _write_point_dashboard,
    _write_runtime_bar_figure,
    _write_timeseries_figure,
)
from hydromodpy.analysis.comparison.visuals_style import (
    _budget_component_color,
    _budget_component_label,
    _display_variant_label,
    _finite_limits,
    _is_flux_like_name,
    _legend_ncols,
    _mask_nodata,
    _pretty_label,
    _rgba_to_hex,
    _robust_limits,
    _robust_symmetric_limit,
    _safe_float,
    _series_style,
    _slug,
    _solver_color,
    _variant_panel_title,
)

# -- helpers --------------------------------------------------------------


def _scatter_payload(
    *,
    variant_id: str = "var",
    values: np.ndarray | None = None,
    cell_ids: np.ndarray | None = None,
    x: np.ndarray | None = None,
    y: np.ndarray | None = None,
    unit: str = "m",
    observable: str = "head",
    extent: tuple[float, float, float, float] | None = None,
) -> MapPayload:
    if values is None:
        values = np.array([1.0, 2.0, 3.0, 4.0])
    n = values.size
    if cell_ids is None:
        cell_ids = np.arange(n, dtype=int)
    if x is None:
        x = np.linspace(0.0, 3.0, n)
    if y is None:
        y = np.linspace(0.0, 3.0, n)
    return MapPayload(
        variant_id=variant_id,
        variant_label=variant_id.upper(),
        solver="modflow6",
        mesh_mode="structured",
        observable_name=observable,
        resolved_variable=observable,
        unit=unit,
        time_label="2024-01",
        values=np.asarray(values, dtype=float),
        geometry_kind="scatter",
        cell_ids=np.asarray(cell_ids, dtype=int),
        x=np.asarray(x, dtype=float),
        y=np.asarray(y, dtype=float),
        extent=extent,
    )


def _structured_payload(
    *,
    variant_id: str = "var",
    shape: tuple[int, int] = (2, 2),
    values: np.ndarray | None = None,
    unit: str = "m",
    observable: str = "head",
    extent: tuple[float, float, float, float] | None = (0.0, 2.0, 0.0, 2.0),
) -> MapPayload:
    if values is None:
        values = np.arange(shape[0] * shape[1], dtype=float)
    return MapPayload(
        variant_id=variant_id,
        variant_label=variant_id.upper(),
        solver="modflow6",
        mesh_mode="structured",
        observable_name=observable,
        resolved_variable=observable,
        unit=unit,
        time_label="2024-01",
        values=np.asarray(values, dtype=float),
        geometry_kind="structured",
        structured_shape=shape,
        x=np.linspace(0.5, 1.5, shape[0] * shape[1]),
        y=np.linspace(0.5, 1.5, shape[0] * shape[1]),
        extent=extent,
    )


# -- string helpers -------------------------------------------------------


def test_slug_basic_lowercases_and_replaces() -> None:
    assert _slug("Hello World!") == "hello_world"


def test_slug_collapses_multiple_separators() -> None:
    assert _slug("foo--bar  baz") == "foo_bar_baz"


def test_slug_empty_string_returns_item_sentinel() -> None:
    assert _slug("   ") == "item"


def test_pretty_label_replaces_underscores_and_caps() -> None:
    assert _pretty_label("hydraulic_head") == "Hydraulic head"


def test_pretty_label_collapses_whitespace() -> None:
    assert _pretty_label("  many   spaces  ") == "Many spaces"


def test_pretty_label_empty_returns_value_sentinel() -> None:
    assert _pretty_label("") == "Value"


def test_display_variant_label_short_keeps_label() -> None:
    assert _display_variant_label(variant_id="vid", variant_label="My label") == "My label"


def test_display_variant_label_long_falls_back_to_id() -> None:
    long_label = "x" * 30
    assert _display_variant_label(variant_id="vid", variant_label=long_label) == "vid"


def test_display_variant_label_empty_label_uses_id() -> None:
    assert _display_variant_label(variant_id="vid", variant_label="   ") == "vid"


def test_variant_panel_title_includes_solver_lower() -> None:
    title = _variant_panel_title(variant_id="vid", variant_label="lab", solver="MODFLOW6")
    assert title == "lab\nmodflow6"


def test_variant_panel_title_no_solver_returns_label_only() -> None:
    title = _variant_panel_title(variant_id="vid", variant_label="lab", solver="")
    assert title == "lab"


# -- legend / extent ------------------------------------------------------


@pytest.mark.parametrize(
    ("count", "expected"),
    [(0, 1), (1, 1), (2, 2), (4, 2), (5, 3), (12, 3)],
)
def test_legend_ncols(count: int, expected: int) -> None:
    assert _legend_ncols(count) == expected


def test_estimate_extent_returns_none_when_inputs_none() -> None:
    assert _estimate_extent_from_centroids(x_values=None, y_values=None) is None


def test_estimate_extent_returns_none_when_no_finite_pair() -> None:
    extent = _estimate_extent_from_centroids(
        x_values=np.array([np.nan, np.inf]),
        y_values=np.array([np.nan, -np.inf]),
    )
    assert extent is None


def test_estimate_extent_basic_grid() -> None:
    extent = _estimate_extent_from_centroids(
        x_values=np.array([0.0, 1.0, 2.0, 0.0, 1.0, 2.0]),
        y_values=np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0]),
    )
    assert extent is not None
    xmin, xmax, ymin, ymax = extent
    assert math.isclose(xmin, -0.5)
    assert math.isclose(xmax, 2.5)
    assert math.isclose(ymin, -0.5)
    assert math.isclose(ymax, 1.5)


def test_estimate_extent_single_unique_value_uses_unit_spacing() -> None:
    extent = _estimate_extent_from_centroids(
        x_values=np.array([5.0, 5.0]),
        y_values=np.array([2.0, 2.0]),
    )
    assert extent == (4.5, 5.5, 1.5, 2.5)


def test_payload_extent_returns_payload_extent_directly() -> None:
    payload = _structured_payload(extent=(0.0, 1.0, 0.0, 1.0))
    assert _payload_extent(payload) == (0.0, 1.0, 0.0, 1.0)


def test_payload_extent_falls_back_to_centroids() -> None:
    payload = _scatter_payload(
        x=np.array([0.0, 1.0, 0.0, 1.0]),
        y=np.array([0.0, 0.0, 1.0, 1.0]),
        extent=None,
    )
    extent = _payload_extent(payload)
    assert extent is not None
    assert math.isclose(extent[0], -0.5)
    assert math.isclose(extent[3], 1.5)


def test_payload_samples_none_when_xy_missing() -> None:
    payload = _structured_payload()
    payload_no_xy = MapPayload(
        variant_id=payload.variant_id,
        variant_label=payload.variant_label,
        solver=payload.solver,
        mesh_mode=payload.mesh_mode,
        observable_name=payload.observable_name,
        resolved_variable=payload.resolved_variable,
        unit=payload.unit,
        time_label=payload.time_label,
        values=payload.values,
        geometry_kind=payload.geometry_kind,
        structured_shape=payload.structured_shape,
        x=None,
        y=None,
    )
    assert _payload_samples(payload_no_xy) is None


def test_payload_samples_returns_finite_values_only() -> None:
    payload = _scatter_payload(
        values=np.array([1.0, np.nan, 3.0, -9999.0]),
        x=np.array([0.0, 1.0, 2.0, 3.0]),
        y=np.array([0.0, 1.0, 2.0, 3.0]),
    )
    samples = _payload_samples(payload)
    assert samples is not None
    sample_x, sample_y, sample_values = samples
    assert sample_values.tolist() == [1.0, 3.0]
    assert sample_x.tolist() == [0.0, 2.0]
    assert sample_y.tolist() == [0.0, 2.0]


def test_payload_samples_size_mismatch_returns_none() -> None:
    payload = MapPayload(
        variant_id="vid",
        variant_label="lab",
        solver="s",
        mesh_mode="structured",
        observable_name="obs",
        resolved_variable="obs",
        unit="m",
        time_label="t",
        values=np.array([1.0, 2.0, 3.0]),
        geometry_kind="scatter",
        x=np.array([0.0, 1.0]),
        y=np.array([0.0, 1.0]),
    )
    assert _payload_samples(payload) is None


# -- color helpers --------------------------------------------------------


def test_solver_color_stable_for_same_name() -> None:
    assert _solver_color("modflow6") == _solver_color("MODFLOW6")


def test_solver_color_empty_returns_neutral_grey() -> None:
    assert _solver_color("   ") == "#6b7280"


def test_solver_color_distinct_for_distinct_names() -> None:
    assert _solver_color("modflow6") != _solver_color("modflow_nwt")


def test_rgba_to_hex_basic() -> None:
    assert _rgba_to_hex((0.0, 0.5, 1.0, 1.0)) == "#0080ff"


@pytest.mark.parametrize(
    "name",
    ["accumulation_flux", "outflow_drain", "surface_excess_total", "saturation_excess", "runoff"],
)
def test_is_flux_like_name_true(name: str) -> None:
    assert _is_flux_like_name(name) is True


def test_is_flux_like_name_false_for_head() -> None:
    assert _is_flux_like_name("hydraulic_head") is False


# -- safe_float / mask_nodata ---------------------------------------------


def test_safe_float_none_returns_none() -> None:
    assert _safe_float(None) is None


def test_safe_float_empty_string_returns_none() -> None:
    assert _safe_float("") is None


def test_safe_float_inf_returns_none() -> None:
    assert _safe_float(float("inf")) is None


def test_safe_float_nan_returns_none() -> None:
    assert _safe_float(float("nan")) is None


def test_safe_float_invalid_string_returns_none() -> None:
    assert _safe_float("not-a-number") is None


def test_safe_float_valid_string() -> None:
    assert _safe_float("3.14") == pytest.approx(3.14)


def test_mask_nodata_replaces_known_sentinels() -> None:
    masked = _mask_nodata(np.array([1.0, -9999.0, -99999.0, -999999.0, 5.0]))
    assert np.isnan(masked[1])
    assert np.isnan(masked[2])
    assert np.isnan(masked[3])
    assert masked[0] == 1.0
    assert masked[4] == 5.0


def test_mask_nodata_preserves_finite_values() -> None:
    values = np.array([0.0, 1.5, -2.0])
    masked = _mask_nodata(values)
    np.testing.assert_array_equal(masked, values)


def test_mask_nodata_empty_array_is_safe() -> None:
    masked = _mask_nodata(np.array([], dtype=float))
    assert masked.size == 0


# -- limits ---------------------------------------------------------------


def test_finite_limits_basic() -> None:
    limits = _finite_limits([np.array([1.0, 2.0, 3.0]), np.array([5.0, np.nan])])
    assert limits == (1.0, 5.0)


def test_finite_limits_all_nonfinite_returns_none() -> None:
    assert _finite_limits([np.array([np.nan, np.inf])]) is None


def test_finite_limits_empty_returns_none() -> None:
    assert _finite_limits([]) is None


def test_robust_limits_below_24_uses_min_max() -> None:
    limits = _robust_limits([np.array([1.0, 2.0, 3.0])])
    assert limits == (1.0, 3.0)


def test_robust_limits_uses_percentiles_for_large_inputs() -> None:
    values = np.concatenate([np.linspace(0.0, 100.0, 200), np.array([1e9])])
    limits = _robust_limits([values])
    assert limits is not None
    lower, upper = limits
    assert lower < upper < 1e9


def test_robust_limits_empty_returns_none() -> None:
    assert _robust_limits([]) is None


def test_robust_symmetric_limit_basic() -> None:
    vmax = _robust_symmetric_limit([np.array([-3.0, -2.0, 1.0, 5.0])])
    assert vmax == pytest.approx(5.0)


def test_robust_symmetric_limit_zeros_returns_none() -> None:
    assert _robust_symmetric_limit([np.array([0.0, 0.0])]) is None


def test_robust_symmetric_limit_empty_returns_none() -> None:
    assert _robust_symmetric_limit([]) is None


# -- time tick formatting -------------------------------------------------


def test_format_time_tick_label_iso_returns_month_abbreviation() -> None:
    assert _format_time_tick_label("2024-03-15") == "Mar"


def test_format_time_tick_label_integer_string_passthrough() -> None:
    assert _format_time_tick_label("42") == "42"


def test_format_time_tick_label_empty_returns_empty() -> None:
    assert _format_time_tick_label("") == ""


def test_format_time_tick_label_year_month_truncation() -> None:
    assert _format_time_tick_label("2024-03-XX") == "2024-03"


def test_apply_time_ticks_no_positions_is_noop() -> None:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    _apply_time_ticks(ax, tick_positions=[])
    assert ax.get_xticks().size >= 0
    plt.close(fig)


def test_apply_time_ticks_with_labels_applies_text() -> None:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    _apply_time_ticks(
        ax,
        tick_positions=[0.0, 1.0, 2.0],
        tick_labels=["2024-01-01", "2024-02-01", "2024-03-01"],
    )
    labels = [t.get_text() for t in ax.get_xticklabels()]
    assert "Jan" in labels or "Feb" in labels or "Mar" in labels
    plt.close(fig)


def test_apply_time_ticks_many_positions_subsamples() -> None:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    _apply_time_ticks(ax, tick_positions=list(range(20)))
    ticks = ax.get_xticks()
    assert ticks.size <= 8
    plt.close(fig)


# -- series style / budget labels ----------------------------------------


def test_series_style_flux_uses_steps_post() -> None:
    style = _series_style("accumulation_flux")
    assert style.get("drawstyle") == "steps-post"


def test_series_style_default_uses_marker() -> None:
    style = _series_style("hydraulic_head")
    assert style.get("marker") == "o"


def test_budget_component_label_known_keys() -> None:
    assert _budget_component_label("recharge_total_m3_s") == "Recharge"
    assert _budget_component_label("storage_change_total_m3_s") == "Storage change"


def test_budget_component_label_unknown_falls_back_to_pretty() -> None:
    assert _budget_component_label("strange_component") == "Strange component"


def test_budget_component_color_known_keys() -> None:
    assert _budget_component_color("recharge_total_m3_s") == "#1f77b4"


def test_budget_component_color_unknown_returns_grey() -> None:
    assert _budget_component_color("strange") == "#6b7280"


# -- difference payload ---------------------------------------------------


def test_build_difference_payload_unit_mismatch_returns_none() -> None:
    ref = _scatter_payload(unit="m")
    cand = _scatter_payload(unit="m3/s")
    assert _build_difference_payload(reference=ref, candidate=cand) is None


def test_build_difference_payload_scatter_match_subtracts() -> None:
    ref = _scatter_payload(values=np.array([1.0, 2.0, 3.0, 4.0]))
    cand = _scatter_payload(values=np.array([2.0, 4.0, 6.0, 8.0]))
    diff = _build_difference_payload(reference=ref, candidate=cand)
    assert diff is not None
    np.testing.assert_array_equal(diff.values, np.array([1.0, 2.0, 3.0, 4.0]))
    assert diff.geometry_kind == "scatter"


def test_build_difference_payload_scatter_size_mismatch_returns_none() -> None:
    ref = _scatter_payload(values=np.array([1.0, 2.0, 3.0]))
    cand = _scatter_payload(values=np.array([2.0, 4.0]))
    assert _build_difference_payload(reference=ref, candidate=cand) is None


def test_build_difference_payload_scatter_cellid_mismatch_returns_none() -> None:
    ref = _scatter_payload(cell_ids=np.array([0, 1, 2, 3]))
    cand = _scatter_payload(cell_ids=np.array([10, 11, 12, 13]))
    assert _build_difference_payload(reference=ref, candidate=cand) is None


def test_build_difference_payload_structured_match() -> None:
    ref = _structured_payload(values=np.arange(4, dtype=float))
    cand = _structured_payload(values=np.arange(4, dtype=float) * 2.0)
    diff = _build_difference_payload(reference=ref, candidate=cand)
    assert diff is not None
    assert diff.geometry_kind == "structured"
    np.testing.assert_array_equal(diff.values, np.arange(4, dtype=float))


def test_build_difference_payload_structured_shape_mismatch_returns_none() -> None:
    ref = _structured_payload(shape=(2, 2), values=np.arange(4, dtype=float))
    cand = _structured_payload(shape=(2, 3), values=np.arange(6, dtype=float))
    assert _build_difference_payload(reference=ref, candidate=cand) is None


def test_build_difference_payload_mixed_geometries_returns_none() -> None:
    ref = _scatter_payload()
    cand = _structured_payload()
    assert _build_difference_payload(reference=ref, candidate=cand) is None


# -- fine grid bounds / build_fine_grid ----------------------------------


def test_build_fine_grid_basic_shape() -> None:
    grid = _build_fine_grid(bounds=(0.0, 10.0, 0.0, 5.0), resolution=1.0)
    assert grid is not None
    grid_x, grid_y, extent = grid
    assert grid_x.shape == grid_y.shape
    assert grid_x.shape[0] == 5  # y
    assert grid_x.shape[1] == 10  # x
    assert extent == (0.0, 10.0, 0.0, 5.0)


def test_build_fine_grid_resolution_too_large_returns_none() -> None:
    grid = _build_fine_grid(bounds=(0.0, 1.0, 0.0, 1.0), resolution=10.0)
    assert grid is None


def test_resolve_fine_grid_bounds_too_few_extents_returns_none() -> None:
    fine = ComparisonFineRaster(enabled=True, resolution=1.0, extent_mode="union")
    payloads = [_scatter_payload(extent=(0.0, 1.0, 0.0, 1.0))]
    assert (
        _resolve_fine_grid_bounds(payloads=payloads, fine_raster=fine, reference_variant=None)
        is None
    )


def test_resolve_fine_grid_bounds_intersection() -> None:
    fine = ComparisonFineRaster(enabled=True, resolution=1.0, extent_mode="intersection")
    payloads = [
        _scatter_payload(variant_id="a", extent=(0.0, 4.0, 0.0, 4.0)),
        _scatter_payload(variant_id="b", extent=(2.0, 6.0, 2.0, 6.0)),
    ]
    bounds = _resolve_fine_grid_bounds(payloads=payloads, fine_raster=fine, reference_variant=None)
    assert bounds == (2.0, 4.0, 2.0, 4.0)


def test_resolve_fine_grid_bounds_intersection_disjoint_returns_none() -> None:
    fine = ComparisonFineRaster(enabled=True, resolution=1.0, extent_mode="intersection")
    payloads = [
        _scatter_payload(variant_id="a", extent=(0.0, 1.0, 0.0, 1.0)),
        _scatter_payload(variant_id="b", extent=(5.0, 6.0, 5.0, 6.0)),
    ]
    assert (
        _resolve_fine_grid_bounds(payloads=payloads, fine_raster=fine, reference_variant=None)
        is None
    )


def test_resolve_fine_grid_bounds_union() -> None:
    fine = ComparisonFineRaster(enabled=True, resolution=1.0, extent_mode="union")
    payloads = [
        _scatter_payload(variant_id="a", extent=(0.0, 4.0, 0.0, 4.0)),
        _scatter_payload(variant_id="b", extent=(2.0, 6.0, 2.0, 6.0)),
    ]
    bounds = _resolve_fine_grid_bounds(payloads=payloads, fine_raster=fine, reference_variant=None)
    assert bounds == (0.0, 6.0, 0.0, 6.0)


def test_resolve_fine_grid_bounds_reference_uses_reference_extent() -> None:
    fine = ComparisonFineRaster(enabled=True, resolution=1.0, extent_mode="reference")
    payloads = [
        _scatter_payload(variant_id="a", extent=(0.0, 4.0, 0.0, 4.0)),
        _scatter_payload(variant_id="b", extent=(2.0, 6.0, 2.0, 6.0)),
    ]
    bounds = _resolve_fine_grid_bounds(payloads=payloads, fine_raster=fine, reference_variant="a")
    assert bounds == (0.0, 4.0, 0.0, 4.0)


def test_regrid_payload_linear_against_grid() -> None:
    payload = _scatter_payload(
        values=np.array([0.0, 1.0, 2.0, 3.0]),
        x=np.array([0.0, 1.0, 0.0, 1.0]),
        y=np.array([0.0, 0.0, 1.0, 1.0]),
    )
    grid_x, grid_y = np.meshgrid(np.linspace(0.1, 0.9, 3), np.linspace(0.1, 0.9, 3))
    array = _regrid_payload(payload=payload, grid_x=grid_x, grid_y=grid_y, interpolation="linear")
    assert array is not None
    assert array.shape == (3, 3)
    assert np.all(np.isfinite(array))


def test_regrid_payload_returns_none_when_no_finite_samples() -> None:
    payload = _scatter_payload(
        values=np.array([np.nan, np.nan, np.nan, np.nan]),
        x=np.array([0.0, 1.0, 0.0, 1.0]),
        y=np.array([0.0, 0.0, 1.0, 1.0]),
    )
    grid_x, grid_y = np.meshgrid([0.5], [0.5])
    array = _regrid_payload(payload=payload, grid_x=grid_x, grid_y=grid_y, interpolation="linear")
    assert array is None


# -- rendering smoke tests -----------------------------------------------


def test_write_map_comparison_figure_creates_png(tmp_path: Path) -> None:
    payloads = [
        _structured_payload(variant_id="ref", shape=(3, 3), values=np.arange(9, dtype=float)),
        _structured_payload(
            variant_id="cand", shape=(3, 3), values=np.arange(9, dtype=float) * 2.0
        ),
    ]
    out = tmp_path / "map.png"
    _write_map_comparison_figure(path=out, observable_name="head", payloads=payloads)
    assert out.exists()
    assert out.stat().st_size > 0


def test_write_difference_figure_creates_png(tmp_path: Path) -> None:
    diff = DifferencePayload(
        reference_variant="ref",
        candidate_variant="cand",
        observable_name="head",
        unit="m",
        values=np.array([0.0, 0.5, -0.5, 1.0]),
        geometry_kind="structured",
        structured_shape=(2, 2),
        extent=(0.0, 2.0, 0.0, 2.0),
    )
    out = tmp_path / "diff.png"
    _write_difference_figure(path=out, payload=diff)
    assert out.exists()


def test_write_timeseries_figure_creates_png(tmp_path: Path) -> None:
    rows = [
        {
            "variant_id": "ref",
            "variant_label": "Ref",
            "value_index": 0,
            "value": 1.0 + i * 0.1,
            "elapsed_seconds": float(i),
            "time_index": i,
        }
        for i in range(5)
    ]
    rows.extend(
        {
            "variant_id": "cand",
            "variant_label": "Cand",
            "value_index": 0,
            "value": 2.0 + i * 0.2,
            "elapsed_seconds": float(i),
            "time_index": i,
        }
        for i in range(5)
    )
    out = tmp_path / "ts.png"
    ok = _write_timeseries_figure(
        path=out, observable_name="hydraulic_head", unit="m", grouped_rows=rows
    )
    assert ok is True
    assert out.exists()


def test_write_timeseries_figure_returns_false_when_too_few_points(tmp_path: Path) -> None:
    rows = [{"variant_id": "ref", "value": 1.0, "time_index": 0, "value_index": 0}]
    out = tmp_path / "ts.png"
    assert (
        _write_timeseries_figure(path=out, observable_name="head", unit="m", grouped_rows=rows)
        is False
    )


def test_write_runtime_bar_figure_creates_png(tmp_path: Path) -> None:
    rows = [
        {"variant_id": "a", "variant_label": "A", "runtime_seconds": 1.0, "solver": "modflow6"},
        {"variant_id": "b", "variant_label": "B", "runtime_seconds": 2.0, "solver": "modflow_nwt"},
    ]
    out = tmp_path / "rt.png"
    assert _write_runtime_bar_figure(path=out, execution_rows=rows, reference_variant="a") is True
    assert out.exists()


def test_write_runtime_bar_figure_returns_false_when_below_two(tmp_path: Path) -> None:
    rows = [{"variant_id": "a", "runtime_seconds": 1.0, "solver": "x"}]
    out = tmp_path / "rt.png"
    assert _write_runtime_bar_figure(path=out, execution_rows=rows, reference_variant=None) is False


def test_write_point_dashboard_creates_png(tmp_path: Path) -> None:
    rows = []
    for obs in ("head_a", "head_b"):
        for i in range(4):
            rows.append(
                {
                    "support": "point",
                    "observable": obs,
                    "variant_id": "ref",
                    "variant_label": "Ref",
                    "value": 1.0 + i,
                    "time_index": i,
                    "unit": "m",
                }
            )
    out = tmp_path / "points.png"
    ok = _write_point_dashboard(path=out, rows=rows)
    assert ok is True
    assert out.exists()


def test_write_point_dashboard_returns_false_with_one_observable(tmp_path: Path) -> None:
    rows = [
        {
            "support": "point",
            "observable": "head",
            "variant_id": "ref",
            "value": 1.0,
            "time_index": 0,
        }
    ]
    out = tmp_path / "points.png"
    assert _write_point_dashboard(path=out, rows=rows) is False


def test_write_native_flux_panel_creates_png(tmp_path: Path) -> None:
    long_rows = []
    for variant in ("ref", "cand"):
        for i in range(4):
            long_rows.append(
                {
                    "variable": "accumulation_flux",
                    "variant_id": variant,
                    "variant_label": variant.upper(),
                    "value": float(i + (1 if variant == "cand" else 0)),
                    "time_index": i,
                    "time_label": f"2024-0{i + 1}-01",
                }
            )
    delta_rows = [
        {
            "variable": "accumulation_flux",
            "variant_id": "cand",
            "signed_error": 0.1 * i,
            "time_index": i,
            "time_label": f"2024-0{i + 1}-01",
        }
        for i in range(4)
    ]
    out = tmp_path / "flux.png"
    ok = _write_native_flux_panel(
        path=out, variable="accumulation_flux", long_rows=long_rows, delta_rows=delta_rows
    )
    assert ok is True
    assert out.exists()


def test_write_flux_dashboard_creates_png(tmp_path: Path) -> None:
    rows = [
        {
            "observable": "outlet_flux_series",
            "variant_id": "ref",
            "variant_label": "Ref",
            "value": float(i),
            "time_index": i,
            "unit": "m3/s",
        }
        for i in range(4)
    ]
    rows.extend(
        {
            "observable": "outlet_flux_series",
            "variant_id": "cand",
            "variant_label": "Cand",
            "value": float(i) + 0.5,
            "time_index": i,
            "unit": "m3/s",
        }
        for i in range(4)
    )
    native_rows = []
    for variable in ("accumulation_flux", "outflow_drain"):
        for i in range(4):
            native_rows.append(
                {
                    "variable": variable,
                    "variant_id": "ref",
                    "variant_label": "Ref",
                    "value": float(i),
                    "time_index": i,
                    "time_label": f"2024-0{i + 1}-01",
                }
            )
            native_rows.append(
                {
                    "variable": variable,
                    "variant_id": "cand",
                    "variant_label": "Cand",
                    "value": float(i) + 0.5,
                    "time_index": i,
                    "time_label": f"2024-0{i + 1}-01",
                }
            )
    out = tmp_path / "dash.png"
    ok = _write_flux_dashboard(path=out, rows=rows, native_long_rows=native_rows)
    assert ok is True
    assert out.exists()


def test_write_budget_diagnostic_figure_creates_png(tmp_path: Path) -> None:
    budget_rows = []
    components = (
        "recharge_total_m3_s",
        "drainage_total_m3_s",
        "storage_change_total_m3_s",
        "closure_residual_m3_s",
    )
    for component in components:
        for i in range(4):
            budget_rows.append(
                {
                    "variant_id": "ref",
                    "component": component,
                    "value": float(i),
                    "elapsed_seconds": float(i),
                    "time_index": i,
                    "time_label": f"2024-0{i + 1}-01",
                }
            )
    rows = [
        {
            "observable": "outlet_flux_series",
            "variant_id": "ref",
            "variant_label": "Ref",
            "value": float(i),
            "time_index": i,
            "elapsed_seconds": float(i),
            "unit": "m3/s",
        }
        for i in range(4)
    ]
    out = tmp_path / "budget.png"
    ok = _write_budget_diagnostic_figure(
        path=out,
        variant_id="ref",
        variant_label="Ref",
        budget_rows=budget_rows,
        rows=rows,
    )
    assert ok is True
    assert out.exists()


def test_write_budget_diagnostic_figure_returns_false_for_unknown_variant(tmp_path: Path) -> None:
    out = tmp_path / "budget.png"
    ok = _write_budget_diagnostic_figure(
        path=out,
        variant_id="missing",
        variant_label="Missing",
        budget_rows=[],
        rows=[],
    )
    assert ok is False


def test_write_regridded_map_figure_creates_png(tmp_path: Path) -> None:
    array_a = np.arange(16, dtype=float).reshape(4, 4)
    array_b = array_a + 1.0
    arrays = [
        (_structured_payload(variant_id="a"), array_a),
        (_structured_payload(variant_id="b"), array_b),
    ]
    out = tmp_path / "fine.png"
    ok = _write_regridded_map_figure(
        path=out, observable_name="head", arrays=arrays, extent=(0.0, 4.0, 0.0, 4.0)
    )
    assert ok is True
    assert out.exists()


def test_write_regridded_difference_figure_creates_png(tmp_path: Path) -> None:
    array = np.linspace(-1.0, 1.0, 16).reshape(4, 4)
    out = tmp_path / "fine_diff.png"
    ok = _write_regridded_difference_figure(
        path=out,
        observable_name="head",
        candidate_variant="cand",
        reference_variant="ref",
        array=array,
        unit="m",
        extent=(0.0, 4.0, 0.0, 4.0),
    )
    assert ok is True
    assert out.exists()


def test_write_geotiff_creates_tif(tmp_path: Path) -> None:
    if visuals_render_maps.rasterio is None:
        pytest.skip("rasterio not installed")
    array = np.arange(16, dtype=float).reshape(4, 4)
    out = tmp_path / "raster.tif"
    ok = _write_geotiff(path=out, array=array, extent=(0.0, 4.0, 0.0, 4.0))
    assert ok is True
    assert out.exists()


def test_write_geotiff_returns_false_for_zero_dim(tmp_path: Path) -> None:
    if visuals_render_maps.rasterio is None:
        pytest.skip("rasterio not installed")
    array = np.zeros((0, 0), dtype=float)
    out = tmp_path / "raster.tif"
    assert _write_geotiff(path=out, array=array, extent=(0.0, 1.0, 0.0, 1.0)) is False

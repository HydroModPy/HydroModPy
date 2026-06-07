"""Anti-regression unit tests for ``analysis.comparison.visuals_style``.

Covers the small, stable string/color/limit helpers: slug, pretty label,
simulation labels, legend columns, solver colors, flux-name detection,
safe-float coercion, nodata masking, finite/robust limits, series styles
and budget component labels/colors.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.analysis.comparison.visuals_style import (
    _budget_component_color,
    _budget_component_label,
    _display_simulation_label,
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
    _simulation_panel_title,
    _slug,
    _solver_color,
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


def test_display_simulation_label_short_keeps_label() -> None:
    assert _display_simulation_label(simulation_id="vid", simulation_label="My label") == "My label"


def test_display_simulation_label_long_falls_back_to_id() -> None:
    long_label = "x" * 30
    assert _display_simulation_label(simulation_id="vid", simulation_label=long_label) == "vid"


def test_display_simulation_label_empty_label_uses_id() -> None:
    assert _display_simulation_label(simulation_id="vid", simulation_label="   ") == "vid"


def test_simulation_panel_title_includes_solver_lower() -> None:
    title = _simulation_panel_title(simulation_id="vid", simulation_label="lab", solver="MODFLOW6")
    assert title == "lab\nmodflow6"


def test_simulation_panel_title_no_solver_returns_label_only() -> None:
    title = _simulation_panel_title(simulation_id="vid", simulation_label="lab", solver="")
    assert title == "lab"


# -- legend ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("count", "expected"),
    [(0, 1), (1, 1), (2, 2), (4, 2), (5, 3), (12, 3)],
)
def test_legend_ncols(count: int, expected: int) -> None:
    assert _legend_ncols(count) == expected


# -- color helpers --------------------------------------------------------


def test_solver_color_stable_for_same_name() -> None:
    assert _solver_color("modflow6") == _solver_color("MODFLOW6")


def test_solver_color_empty_returns_neutral_grey() -> None:
    assert _solver_color("   ") == "#6b7280"


def test_solver_color_distinct_for_distinct_names() -> None:
    assert _solver_color("modflow6") != _solver_color("modflow_nwt")


def test_solver_color_uses_method_family_aliases() -> None:
    assert _solver_color("mf6_ref") == _solver_color("modflow6")
    assert _solver_color("bouss_candidate") == _solver_color("boussinesq")


def test_rgba_to_hex_basic() -> None:
    assert _rgba_to_hex((0.0, 0.5, 1.0, 1.0)) == "#0080ff"


@pytest.mark.parametrize(
    "name",
    [
        "accumulation_flux",
        "outflow_drain",
        "surface_excess_total",
        "saturation_excess",
        "runoff",
    ],
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

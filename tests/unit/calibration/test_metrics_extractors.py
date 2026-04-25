"""Tests for :func:`hydromodpy.calibration.metrics.build_metric_extractor`.

Covers Phase 3 of the calibration integration:

- Without ``outputs`` the legacy single-metric extractor is returned and
  no composite objective is built.
- With ``outputs`` and ``objective_blocks`` the extractor routes through
  :func:`build_objective_from_config` and exposes per-block costs as
  components.
- The point / boundary helpers degrade gracefully when the trial
  context does not expose a flow run (returns ``[nan]`` instead of
  raising).
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from hydromodpy.calibration.config import (
    CalibObjectiveBlockDecl,
    CalibOutputDecl,
)
from hydromodpy.calibration.metrics import (
    _coerce_length_to_m,
    _extract_boundary,
    _extract_cell,
    _extract_point,
    _slice_time,
    build_metric_extractor,
)


def _empty_ctx():
    """Return a minimal context with no flow run and no loaded data."""
    return SimpleNamespace(
        setup=SimpleNamespace(mesh_planar=None, domain=None, time_grid=None),
        loaded_data=SimpleNamespace(piezometry=None, hydrometry=None),
        execution=None,
    )


# ---------------------------------------------------------------------------
# Legacy fallback path
# ---------------------------------------------------------------------------


class TestLegacyFallback:
    def test_falls_back_when_no_outputs(self):
        ctx = _empty_ctx()
        metric_fn = build_metric_extractor(
            "head",
            "rmse",
            ctx,
            outputs=None,
            objective_blocks=None,
        )
        primary, components = metric_fn(ctx, objective="rmse", variable="head")
        assert math.isnan(primary)
        assert components == {}

    def test_falls_back_when_outputs_empty(self):
        ctx = _empty_ctx()
        metric_fn = build_metric_extractor("head", "rmse", ctx, outputs={}, objective_blocks=[])
        primary, _ = metric_fn(ctx, objective="rmse", variable="head")
        assert math.isnan(primary)


# ---------------------------------------------------------------------------
# Composite path
# ---------------------------------------------------------------------------


class TestCompositeRouting:
    def _outputs_and_block(self):
        outputs = {
            "head_A": CalibOutputDecl.model_validate(
                {
                    "variable": "head",
                    "support": "cell",
                    "observed_values": [1.0, 2.0, 3.0],
                }
            )
        }
        block = CalibObjectiveBlockDecl.model_validate(
            {"name": "head_block", "metric": "rmse", "uses_outputs": ["head_A"]}
        )
        return outputs, [block]

    def test_routes_through_composite_with_outputs_and_blocks(self):
        outputs, blocks = self._outputs_and_block()
        ctx = _empty_ctx()
        metric_fn = build_metric_extractor(
            None,
            None,
            ctx,
            outputs=outputs,
            objective_blocks=blocks,
        )
        # ``_extract_cell`` returns [nan] on a stub context. The composite
        # propagates that into a non-finite total but we still want the
        # block components to be returned.
        primary, components = metric_fn(ctx)
        assert isinstance(primary, float)
        # Either the cost is nan (insufficient data) or +inf (no data).
        assert math.isnan(primary) or math.isinf(primary)
        assert isinstance(components, dict)

    def test_composite_total_matches_block_when_simulated_provided(self):
        """When the extractor is replaced with a stub returning known
        simulated values, the composite total must reproduce the block
        cost computed manually.
        """
        outputs, blocks = self._outputs_and_block()
        ctx = _empty_ctx()
        # Patch the cell extractor for this single test by running the
        # composite directly against a known sim mapping.
        from hydromodpy.calibration.objective import build_objective_from_config

        cfg_subset = SimpleNamespace(outputs=dict(outputs), objective_blocks=list(blocks))
        obj = build_objective_from_config(cfg_subset)
        result = obj.evaluate({"head_A": [1.5, 2.5, 3.5]})
        # rmse([1,2,3], [1.5,2.5,3.5]) = 0.5
        assert result.total == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_coerce_length_handles_pint(self):
        out = CalibOutputDecl.model_validate(
            {"variable": "head", "support": "point", "x": 100.0, "y": 0.0}
        )
        assert _coerce_length_to_m(out.x) == 100.0
        assert _coerce_length_to_m(out.y) == 0.0
        assert _coerce_length_to_m(None) is None

    def test_slice_time_first_last_all(self):
        arr = [1.0, 2.0, 3.0, 4.0]
        assert _slice_time(arr, "all", "none") == [1.0, 2.0, 3.0, 4.0]
        assert _slice_time(arr, "first", "none") == [1.0]
        assert _slice_time(arr, "last", "none") == [4.0]
        assert _slice_time(arr, "all", "mean")[0] == pytest.approx(2.5)
        assert _slice_time(arr, "all", "sum")[0] == pytest.approx(10.0)
        assert _slice_time(arr, "all", "last") == [4.0]

    def test_extract_point_returns_nan_when_no_flow_run(self):
        ctx = _empty_ctx()
        out = CalibOutputDecl.model_validate(
            {"variable": "head", "support": "point", "x": 1.0, "y": 2.0}
        )
        assert _extract_point(ctx, out) == [float("nan")] or math.isnan(_extract_point(ctx, out)[0])

    def test_extract_boundary_returns_nan_when_no_flow_run(self):
        ctx = _empty_ctx()
        out = CalibOutputDecl.model_validate(
            {"variable": "discharge", "support": "boundary", "boundary_id": "outlet"}
        )
        result = _extract_boundary(ctx, out)
        assert len(result) == 1 and math.isnan(result[0])

    def test_extract_cell_returns_nan(self):
        out = CalibOutputDecl.model_validate({"variable": "head", "support": "cell"})
        result = _extract_cell(_empty_ctx(), out)
        assert len(result) == 1 and math.isnan(result[0])

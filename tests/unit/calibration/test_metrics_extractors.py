"""Tests for :func:`hydromodpy.calibration.metrics.build_metric_extractor`.

Covers Phase 3 of the calibration integration:

- Without ``outputs`` the legacy single-metric extractor is returned and
  no composite objective is built.
- With ``outputs`` and ``objective_blocks`` the extractor routes through
  :func:`build_objective_from_config` and exposes per-block costs as
  components.
- The point / boundary helpers fail loudly when the trial context does
  not expose a flow run.
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from hydromodpy.calibration import metrics as metrics_module
from hydromodpy.calibration.config import (
    CalibObjectiveBlockDecl,
    CalibOutputDecl,
)
from hydromodpy.calibration.metrics import (
    ObservedSeries,
    _coerce_length_to_m,
    _extract_boundary,
    _extract_cell,
    _extract_point,
    _resolve_station_cells,
    _score,
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
        with pytest.raises(NotImplementedError, match="No flow solver adapter"):
            metric_fn(ctx, objective="rmse", variable="head")

    def test_falls_back_when_outputs_empty(self):
        ctx = _empty_ctx()
        metric_fn = build_metric_extractor("head", "rmse", ctx, outputs={}, objective_blocks=[])
        with pytest.raises(NotImplementedError, match="No flow solver adapter"):
            metric_fn(ctx, objective="rmse", variable="head")


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
                    "row": 0,
                    "col": 0,
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
        with pytest.raises(RuntimeError, match="Output 'head_A' extraction failed"):
            metric_fn(ctx)

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

    def test_score_raises_when_series_do_not_overlap(self):
        obs = pd.Series([1.0], index=pd.DatetimeIndex(["2020-01-01"]))
        sim = pd.Series([1.0], index=pd.DatetimeIndex(["2021-01-01"]))
        with pytest.raises(ValueError, match="No overlapping finite"):
            _score(obs, sim, "rmse")

    def test_extract_point_raises_when_no_flow_run(self):
        ctx = _empty_ctx()
        out = CalibOutputDecl.model_validate(
            {"variable": "head", "support": "point", "x": 1.0, "y": 2.0}
        )
        with pytest.raises(NotImplementedError, match="No flow solver adapter"):
            _extract_point(ctx, out)

    def test_extract_boundary_raises_when_no_flow_run(self):
        ctx = _empty_ctx()
        out = CalibOutputDecl.model_validate(
            {"variable": "discharge", "support": "boundary", "boundary_id": "outlet"}
        )
        with pytest.raises(NotImplementedError, match="No flow solver adapter"):
            _extract_boundary(ctx, out)

    def test_extract_boundary_requires_adapter_boundary_filter(self, monkeypatch):
        class _Adapter:
            def extract_calibration_series(self, ctx, store, *, variable, time_index=None):
                del ctx, store, variable, time_index
                return pd.Series([1.0])

        run_ctx = SimpleNamespace(run=SimpleNamespace(solver="fake_solver"))
        monkeypatch.setattr(
            metrics_module,
            "_resolve_flow_adapter",
            lambda ctx: (_Adapter(), run_ctx),
        )
        out = CalibOutputDecl.model_validate(
            {"variable": "discharge", "support": "boundary", "boundary_id": "outlet"}
        )
        with pytest.raises(NotImplementedError, match="cannot filter calibration boundary_id"):
            _extract_boundary(_empty_ctx(), out)

    def test_extract_cell_raises_when_no_flow_run(self):
        out = CalibOutputDecl.model_validate(
            {"variable": "head", "support": "cell", "row": 0, "col": 1}
        )
        with pytest.raises(NotImplementedError, match="No flow solver adapter"):
            _extract_cell(_empty_ctx(), out)

    def test_station_cells_uses_structural_metadata_without_mesh(self):
        rec = SimpleNamespace(station_id="P1", cell_ij=(3, 4, 2))
        ctx = SimpleNamespace(
            setup=SimpleNamespace(mesh_planar=None, domain=None),
            loaded_data=SimpleNamespace(piezometry=SimpleNamespace(points=[rec])),
        )
        observed = [
            ObservedSeries(
                station_id="P1",
                variable="head",
                series=pd.Series([1.0], index=pd.DatetimeIndex(["2020-01-01"])),
            )
        ]

        assert _resolve_station_cells(ctx, observed) == {"P1": (2, 3, 4)}

"""Composite routing tests targeted at the CLI wiring boundary.

The CLI builds the metric extractor by passing
``cfg.outputs or None`` and ``cfg.objective_blocks or None`` so the
composite path is engaged whenever the user declares them. These tests
verify that:

- Calling :func:`build_metric_extractor` with the same arguments the CLI
  would pass yields a callable that returns the composite components when
  fed simulated values directly via the underlying objective.
- Calling :func:`build_metric_extractor` with ``cfg.outputs is None``
  (typical for the bare-minimum TOML) returns the single-metric extractor.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.metrics import build_metric_extractor
from hydromodpy.calibration.objective import build_objective_from_config


def _empty_ctx():
    return SimpleNamespace(
        setup=SimpleNamespace(mesh_planar=None, domain=None, time_grid=None),
        loaded_data=SimpleNamespace(piezometry=None, hydrometry=None),
        execution=None,
    )


class TestCliWiring:
    def test_cli_args_engage_composite_when_blocks_declared(self):
        cfg = CalibrationConfig.model_validate(
            {
                "method": "grid",
                "variable": "head",
                "objective": "rmse",
                "outputs": {
                    "head_A": {
                        "variable": "head",
                        "support": "cell",
                        "row": 0,
                        "col": 0,
                        "observed_values": [1.0, 2.0, 3.0],
                    }
                },
                "objective_blocks": [
                    {
                        "name": "head_block",
                        "metric": "rmse",
                        "uses_outputs": ["head_A"],
                    }
                ],
            }
        )
        ctx = _empty_ctx()
        metric_fn = build_metric_extractor(
            cfg.variable,
            cfg.objective,
            ctx,
            outputs=cfg.outputs or None,
            objective_blocks=cfg.objective_blocks or None,
        )
        with pytest.raises(RuntimeError, match="Output 'head_A' extraction failed"):
            metric_fn(ctx)

    def test_composite_evaluates_when_simulated_provided(self):
        """End-to-end check: feed simulated values directly into the
        composite (bypassing extraction) and verify the cost matches the
        block metric. This guards against regressions in
        ``build_objective_from_config`` wiring."""
        cfg = CalibrationConfig.model_validate(
            {
                "outputs": {
                    "head_A": {
                        "variable": "head",
                        "support": "cell",
                        "row": 0,
                        "col": 0,
                        "observed_values": [10.0, 20.0, 30.0],
                    }
                },
                "objective_blocks": [{"name": "b", "metric": "rmse", "uses_outputs": ["head_A"]}],
            }
        )
        obj = build_objective_from_config(cfg)
        result = obj.evaluate({"head_A": [12.0, 22.0, 32.0]})
        assert result.total == pytest.approx(2.0)

    def test_cli_args_keep_legacy_when_no_blocks(self):
        cfg = CalibrationConfig.model_validate(
            {"method": "grid", "variable": "head", "objective": "rmse"}
        )
        ctx = _empty_ctx()
        metric_fn = build_metric_extractor(
            cfg.variable,
            cfg.objective,
            ctx,
            outputs=cfg.outputs or None,
            objective_blocks=cfg.objective_blocks or None,
        )
        with pytest.raises(NotImplementedError, match="No flow solver adapter"):
            metric_fn(ctx, objective="rmse", variable="head")

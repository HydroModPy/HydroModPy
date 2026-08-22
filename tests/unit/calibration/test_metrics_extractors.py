"""Tests for :func:`hydromodpy.calibration.metrics.build_metric_extractor`.

Covers Phase 3 of the calibration integration:

- Without ``outputs`` the single-metric extractor is returned and no
  composite objective is built. This is the standard TOML route, taken
  whenever no ``objective_blocks`` are declared.
- With ``outputs`` and ``objective_blocks`` the extractor routes through
  :func:`build_objective_from_config` and exposes per-block costs as
  components.
- The point / boundary helpers fail loudly when the trial context does
  not expose a flow run.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.calibration.config import (
    CalibObjectiveBlockDecl,
    validate_calib_output,
)
from hydromodpy.calibration.metrics import (
    ObservedSeries,
    build_metric_extractor,
)
from hydromodpy.calibration.metrics import solver_extract as _solver_extract_module
from hydromodpy.calibration.metrics.composite import _build_composite_metric_extractor  # noqa: F401
from hydromodpy.calibration.metrics.scalar import score as _score
from hydromodpy.calibration.metrics.solver_extract import (
    _coerce_length_to_m,
)
from hydromodpy.calibration.metrics.solver_extract import (
    extract_outputs as _extract_outputs,
)
from hydromodpy.calibration.metrics.solver_extract import (
    observable_request_for_output as _request_for_output,
)
from hydromodpy.calibration.metrics.solver_extract import (
    resolve_station_cells as _resolve_station_cells,
)
from hydromodpy.calibration.metrics.solver_extract import (
    slice_time as _slice_time,
)
from hydromodpy.core.contracts.observables import ObservableResult


def _empty_ctx():
    """Return a minimal context with no flow run and no loaded data."""
    return SimpleNamespace(
        setup=SimpleNamespace(mesh_planar=None, domain=None, time_grid=None),
        loaded_data=SimpleNamespace(piezometry=None, hydrometry=None),
        execution=None,
    )


# ---------------------------------------------------------------------------
# Single-metric path (no objective_blocks declared)
# ---------------------------------------------------------------------------


class TestSingleMetricPath:
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
            "head_A": validate_calib_output(
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
        # Extraction is one batch now, so a context with no flow run fails once
        # for the batch rather than once per output.
        with pytest.raises(NotImplementedError, match="No flow solver adapter"):
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
        from hydromodpy.calibration.optim.objective import build_objective_from_config

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
        out = validate_calib_output({"variable": "head", "support": "point", "x": 100.0, "y": 0.0})
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

    def test_extract_outputs_raises_when_no_flow_run(self):
        out = validate_calib_output({"variable": "head", "support": "point", "x": 1.0, "y": 2.0})
        with pytest.raises(NotImplementedError, match="No flow solver adapter"):
            _extract_outputs(_empty_ctx(), {"head_A": out})

    def test_boundary_output_becomes_a_keyed_request(self):
        out = validate_calib_output(
            {"variable": "discharge", "support": "boundary", "boundary_id": "outlet"}
        )
        request = _request_for_output("q", out, _empty_ctx())
        assert (request.id, request.name, request.support) == ("q", "discharge", "boundary")
        assert request.key == "outlet"

    def test_lake_output_carries_its_quantity_and_lake(self):
        out = validate_calib_output(
            {"variable": "volume", "support": "lake", "lake_id": "lac0", "time": "last"}
        )
        request = _request_for_output("lake", out, _empty_ctx())
        assert (request.name, request.support, request.key) == ("volume", "lake", "lac0")
        assert request.times == "last"

    def test_cell_output_carries_its_cell(self):
        out = validate_calib_output(
            {"variable": "head", "support": "cell", "layer": 2, "row": 0, "col": 1}
        )
        request = _request_for_output("h", out, _empty_ctx())
        assert (request.support, request.cell) == ("cell", (2, 0, 1))

    def test_cell_output_without_row_col_is_refused(self):
        # A flat cell_id passes the schema but no solver exposes that selector.
        out = validate_calib_output({"variable": "head", "support": "cell", "cell_id": 7})
        with pytest.raises(NotImplementedError, match="needs row and col"):
            _request_for_output("h", out, _empty_ctx())

    def test_extract_outputs_batches_every_declaration_in_one_call(self, monkeypatch):
        seen = {}

        class _Adapter:
            def extract_observables(self, ctx, store, requests, *, time_index=None):
                del ctx, store, time_index
                seen["n_calls"] = seen.get("n_calls", 0) + 1
                seen["ids"] = [request.id for request in requests]
                return {
                    request.id: ObservableResult(
                        request_id=request.id,
                        values=np.array([1.0, 2.0, 3.0]),
                        units="m",
                    )
                    for request in requests
                }

        run_ctx = SimpleNamespace(run=SimpleNamespace(solver="fake_solver"))
        monkeypatch.setattr(
            _solver_extract_module,
            "resolve_flow_adapter",
            lambda ctx: (_Adapter(), run_ctx),
        )
        outputs = {
            "lake": validate_calib_output(
                {"variable": "stage", "support": "lake", "lake_id": "lac0", "time": "last"}
            ),
            "cell": validate_calib_output(
                {"variable": "head", "support": "cell", "row": 0, "col": 1}
            ),
        }

        simulated, diagnostics = _extract_outputs(_empty_ctx(), outputs)

        # Two outputs, one adapter call: that is what the batch buys.
        assert seen["n_calls"] == 1
        assert seen["ids"] == ["lake", "cell"]
        assert simulated["lake"] == [3.0]
        assert simulated["cell"] == [1.0, 2.0, 3.0]
        # Only a network output produces diagnostics beside its values.
        assert diagnostics == {}

    def test_extract_outputs_names_the_output_whose_declaration_is_wrong(self, monkeypatch):
        class _Adapter:
            def extract_observables(self, ctx, store, requests, *, time_index=None):
                raise AssertionError("must not be reached")

        run_ctx = SimpleNamespace(run=SimpleNamespace(solver="fake_solver"))
        monkeypatch.setattr(
            _solver_extract_module,
            "resolve_flow_adapter",
            lambda ctx: (_Adapter(), run_ctx),
        )
        out = validate_calib_output({"variable": "head", "support": "cell", "cell_id": 7})
        with pytest.raises(RuntimeError, match="Output 'h' extraction failed"):
            _extract_outputs(_empty_ctx(), {"h": out})

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

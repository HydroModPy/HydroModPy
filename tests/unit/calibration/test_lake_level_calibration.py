"""Tests for the lake-level (LAK stage) calibration target.

Covers the encapsulated feature added to calibrate a MODFLOW 6 LAK lake stage:

- schema: the ``lake`` output support variant and its discrimination,
- extractor: ``extract_lake_series`` reading the LAK obs CSV + JSON sidecar,
- bridge: ``extract_lake`` and the ``lake_id`` threading guard,
- observations: ``load_observed`` mapping ``lake_level`` to the ``lake_levels``
  data family,
- single-metric path: the ``variable="lake_level"`` metric extractor,
  time-aligned. This is the standard TOML route taken when no
  ``objective_blocks`` are declared.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.calibration.config import CalibOutputLake, validate_calib_output
from hydromodpy.calibration.metrics import build_metric_extractor
from hydromodpy.calibration.metrics import composite as _composite_module
from hydromodpy.calibration.metrics import solver_extract as _solver_extract_module
from hydromodpy.calibration.metrics.series import load_observed
from hydromodpy.calibration.metrics.solver_extract import extract_outputs as _extract_outputs
from hydromodpy.core.contracts.observables import (
    ObservableRequest,
    ObservableResult,
)
from hydromodpy.core.exceptions import ObservableNotAvailableError
from hydromodpy.solver.modflow6.adapters.flow import Modflow6FlowAdapter
from hydromodpy.solver.modflow6.extractors.lake import extract_lake_series

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class TestSchema:
    def test_lake_output_discriminates_on_support(self):
        out = validate_calib_output(
            {"support": "lake", "lake_id": "lac0", "observed_values": [1.0, 2.0]}
        )
        assert isinstance(out, CalibOutputLake)
        assert out.lake_id == "lac0"
        assert out.variable == "stage"
        assert out.time == "all"
        assert out.reducer == "none"

    def test_lake_output_requires_lake_id(self):
        with pytest.raises(ValueError, match="lake_id"):
            validate_calib_output({"support": "lake"})

    def test_lake_output_rejects_unknown_variable(self):
        with pytest.raises(ValueError):
            validate_calib_output({"support": "lake", "lake_id": "lac0", "variable": "inflow"})

    @pytest.mark.parametrize("quantity", ["stage", "volume", "surface_area"])
    def test_lake_output_accepts_every_lak_state(self, quantity):
        out = validate_calib_output({"support": "lake", "lake_id": "lac0", "variable": quantity})
        assert out.variable == quantity


# ---------------------------------------------------------------------------
# Extractor (LAK obs CSV + sidecar)
# ---------------------------------------------------------------------------


def _write_lake_outputs(
    output_dir: Path,
    model_name: str,
    *,
    lake_id: str = "lac0",
    stages: tuple[float, ...] = (86.97, 87.01, 87.05),
) -> None:
    """Write a minimal LAK obs CSV + JSON sidecar for one lake."""
    obs_csv = f"{model_name}.lak.obs.csv"
    meta = {
        "obs_csv": obs_csv,
        "budgetcsv": None,
        "entries": [
            {"obsname": f"{lake_id}_stage", "lake_id": lake_id, "quantity": "stage"},
            {"obsname": f"{lake_id}_volume", "lake_id": lake_id, "quantity": "volume"},
        ],
    }
    (output_dir / f"{model_name}.lak.meta.json").write_text(json.dumps(meta), encoding="utf-8")
    lines = [f"time,{lake_id}_stage,{lake_id}_volume"]
    for step, stage in enumerate(stages, start=1):
        lines.append(f"{float(step)},{stage},{stage * 1000.0}")
    (output_dir / obs_csv).write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestExtractor:
    def test_reads_stage_column_positional(self, tmp_path: Path):
        _write_lake_outputs(tmp_path, "m", stages=(86.97, 87.01, 87.05))
        series = extract_lake_series(tmp_path, "m", lake_id="lac0")
        assert list(series.values) == pytest.approx([86.97, 87.01, 87.05])
        assert series.name == "stage"

    def test_applies_time_index_when_length_matches(self, tmp_path: Path):
        _write_lake_outputs(tmp_path, "m", stages=(86.97, 87.01, 87.05))
        idx = pd.DatetimeIndex(["2007-01-01", "2007-01-02", "2007-01-03"])
        series = extract_lake_series(tmp_path, "m", lake_id="lac0", time_index=idx)
        assert series.index.equals(idx)
        assert series.loc["2007-01-02"] == pytest.approx(87.01)

    def test_ignores_mismatched_time_index(self, tmp_path: Path):
        _write_lake_outputs(tmp_path, "m", stages=(86.97, 87.01, 87.05))
        idx = pd.DatetimeIndex(["2007-01-01"])
        series = extract_lake_series(tmp_path, "m", lake_id="lac0", time_index=idx)
        assert not isinstance(series.index, pd.DatetimeIndex)

    def test_reads_volume_state_quantity(self, tmp_path: Path):
        _write_lake_outputs(tmp_path, "m", stages=(10.0,))
        series = extract_lake_series(tmp_path, "m", lake_id="lac0", quantity="volume")
        assert list(series.values) == pytest.approx([10000.0])

    def test_unknown_lake_raises_keyerror(self, tmp_path: Path):
        _write_lake_outputs(tmp_path, "m")
        with pytest.raises(KeyError, match="other_lake"):
            extract_lake_series(tmp_path, "m", lake_id="other_lake")

    def test_missing_sidecar_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError, match="sidecar"):
            extract_lake_series(tmp_path, "m", lake_id="lac0")

    def test_unsupported_quantity_raises(self, tmp_path: Path):
        _write_lake_outputs(tmp_path, "m")
        with pytest.raises(NotImplementedError, match="Lake calibration supports"):
            extract_lake_series(tmp_path, "m", lake_id="lac0", quantity="inflow")


# ---------------------------------------------------------------------------
# Adapter branch
# ---------------------------------------------------------------------------


class TestAdapterBranch:
    def _ctx(self, tmp_path: Path):
        return SimpleNamespace(
            run=SimpleNamespace(id="r1"),
            state=SimpleNamespace(
                execution=SimpleNamespace(
                    output_dirs_by_run_id={"r1": tmp_path},
                    models_by_run_id={
                        "r1": SimpleNamespace(model_output_name="m", solver_mesh=None)
                    },
                )
            ),
        )

    def test_lake_request_needs_a_lake_key(self):
        # The contract refuses a lake request with no lake, so the adapter is
        # never reached with an unusable request.
        with pytest.raises(ValueError, match="needs a key"):
            ObservableRequest(id="l", name="stage", support="lake")

    def test_lake_stage_reads_series(self, tmp_path: Path):
        _write_lake_outputs(tmp_path, "m", stages=(86.0, 87.0))
        adapter = Modflow6FlowAdapter()
        results = adapter.extract_observables(
            self._ctx(tmp_path),
            None,
            [ObservableRequest(id="l", name="stage", support="lake", key="lac0")],
        )
        assert list(results["l"].values) == pytest.approx([86.0, 87.0])
        assert results["l"].units == "m"

    def test_lake_volume_reads_the_volume_column(self, tmp_path: Path):
        """The request name selects the LAK state, not just the stage column."""
        _write_lake_outputs(tmp_path, "m", stages=(86.0, 87.0))
        adapter = Modflow6FlowAdapter()
        results = adapter.extract_observables(
            self._ctx(tmp_path),
            None,
            [ObservableRequest(id="l", name="volume", support="lake", key="lac0")],
        )
        assert list(results["l"].values) == pytest.approx([86000.0, 87000.0])
        assert results["l"].units == "m3"

    def test_two_lake_states_come_back_from_one_call(self, tmp_path: Path):
        _write_lake_outputs(tmp_path, "m", stages=(86.0, 87.0))
        adapter = Modflow6FlowAdapter()
        results = adapter.extract_observables(
            self._ctx(tmp_path),
            None,
            [
                ObservableRequest(id="stage", name="stage", support="lake", key="lac0"),
                ObservableRequest(id="vol", name="volume", support="lake", key="lac0"),
            ],
        )
        assert sorted(results) == ["stage", "vol"]
        assert list(results["stage"].values) == pytest.approx([86.0, 87.0])
        assert list(results["vol"].values) == pytest.approx([86000.0, 87000.0])

    def test_unknown_lake_state_is_refused_by_name(self, tmp_path: Path):
        adapter = Modflow6FlowAdapter()
        with pytest.raises(ObservableNotAvailableError, match="inflow"):
            adapter.extract_observables(
                self._ctx(tmp_path),
                None,
                [ObservableRequest(id="l", name="inflow", support="lake", key="lac0")],
            )

    def test_last_timestep_only_is_honoured(self, tmp_path: Path):
        _write_lake_outputs(tmp_path, "m", stages=(86.0, 87.0))
        adapter = Modflow6FlowAdapter()
        results = adapter.extract_observables(
            self._ctx(tmp_path),
            None,
            [ObservableRequest(id="l", name="stage", support="lake", key="lac0", times="last")],
        )
        assert list(results["l"].values) == pytest.approx([87.0])


# ---------------------------------------------------------------------------
# Bridge: extract_lake + lake_id threading guard
# ---------------------------------------------------------------------------


class _LakeAdapter:
    """Stub solver adapter that serves any lake request with a fixed series."""

    def extract_observables(self, ctx, store, requests, *, time_index=None):
        del ctx, store, time_index
        return {
            request.id: ObservableResult(
                request_id=request.id,
                values=np.array([1.0, 2.0, 3.0]),
                units="m",
            )
            for request in requests
        }


class _NoLakeAdapter:
    """Stub adapter that refuses lake observables, as MODFLOW-NWT does."""

    def extract_observables(self, ctx, store, requests, *, time_index=None):
        del ctx, store, time_index
        for request in requests:
            if request.support == "lake":
                raise ObservableNotAvailableError(
                    f"this backend does not produce observable {request.name!r} on support "
                    f"{request.support!r}."
                )
        return {}


class TestBridge:
    def test_lake_output_raises_without_flow_run(self):
        ctx = SimpleNamespace(execution=None)
        out = validate_calib_output({"support": "lake", "lake_id": "lac0"})
        with pytest.raises(NotImplementedError, match="No flow solver adapter"):
            _extract_outputs(ctx, {"lake": out})

    def test_lake_output_slices_last(self, monkeypatch):
        run_ctx = SimpleNamespace(run=SimpleNamespace(solver="modflow6"))
        monkeypatch.setattr(
            _solver_extract_module,
            "resolve_flow_adapter",
            lambda ctx: (_LakeAdapter(), run_ctx),
        )
        out = validate_calib_output(
            {"support": "lake", "lake_id": "lac0", "time": "last", "reducer": "last"}
        )
        assert _extract_outputs(SimpleNamespace(), {"lake": out}) == {"lake": [3.0]}

    def test_a_backend_without_lakes_refuses_by_name(self, monkeypatch):
        # The refusal now comes from the backend itself rather than from the
        # caller reading its signature.
        run_ctx = SimpleNamespace(run=SimpleNamespace(solver="modflow_nwt"))
        monkeypatch.setattr(
            _solver_extract_module,
            "resolve_flow_adapter",
            lambda ctx: (_NoLakeAdapter(), run_ctx),
        )
        out = validate_calib_output({"support": "lake", "lake_id": "lac0"})
        with pytest.raises(ObservableNotAvailableError, match="on support 'lake'"):
            _extract_outputs(SimpleNamespace(), {"lake": out})

    @pytest.mark.parametrize("declared", ["stage", "volume", "surface_area"])
    def test_declared_quantity_reaches_the_adapter(self, monkeypatch, declared):
        """The config quantity is what the adapter is asked for, not a fixed stage."""
        seen: dict[str, str] = {}

        class _Recorder:
            def extract_observables(self, ctx, store, requests, *, time_index=None):
                del ctx, store, time_index
                seen["name"] = requests[0].name
                seen["key"] = requests[0].key
                seen["support"] = requests[0].support
                return {
                    requests[0].id: ObservableResult(
                        request_id=requests[0].id,
                        values=np.array([1.0]),
                        units="m",
                    )
                }

        run_ctx = SimpleNamespace(run=SimpleNamespace(solver="modflow6"))
        monkeypatch.setattr(
            _solver_extract_module,
            "resolve_flow_adapter",
            lambda ctx: (_Recorder(), run_ctx),
        )
        out = validate_calib_output({"support": "lake", "lake_id": "lac0", "variable": declared})
        _extract_outputs(SimpleNamespace(), {"lake": out})
        # No composed lake_<quantity> string any more: the state is the name and
        # the lake is the key.
        assert seen == {"name": declared, "key": "lac0", "support": "lake"}


# ---------------------------------------------------------------------------
# Observations: load_observed lake_level mapping
# ---------------------------------------------------------------------------


def _lake_levels_ctx(station_id: str = "lac0"):
    df = pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03"]),
            "value": [10.0, 11.0, 12.0],
        }
    )
    rec = SimpleNamespace(station_id=station_id, variable="lake_level", data=df)
    return SimpleNamespace(
        setup=SimpleNamespace(time_grid=None),
        loaded_data=SimpleNamespace(lake_levels=SimpleNamespace(points=[rec])),
    )


class TestLoadObserved:
    def test_maps_lake_level_to_lake_levels_family(self):
        ctx = _lake_levels_ctx()
        observed = load_observed(ctx, "lake_level")
        assert len(observed) == 1
        assert observed[0].station_id == "lac0"
        assert observed[0].variable == "lake_level"
        assert list(observed[0].series.values) == pytest.approx([10.0, 11.0, 12.0])

    def test_unknown_variable_returns_empty(self):
        ctx = _lake_levels_ctx()
        assert load_observed(ctx, "salinity") == []


# ---------------------------------------------------------------------------
# Single-metric path: variable="lake_level" metric extractor (time-aligned)
# ---------------------------------------------------------------------------


class TestSingleMetricLakeLevelPath:
    def test_metric_fn_scores_time_aligned_stage(self, monkeypatch):
        ctx = _lake_levels_ctx()
        metric_fn = build_metric_extractor(
            "lake_level", "rmse", ctx, outputs=None, objective_blocks=None
        )

        observed_dates = pd.DatetimeIndex(["2020-01-01", "2020-01-02", "2020-01-03"])

        class _AlignedAdapter:
            def extract_observables(self, ctx, store, requests, *, time_index=None):
                del ctx, store, time_index
                # Observed is [10, 11, 12]; offset by 0.5 -> rmse == 0.5.
                return {
                    request.id: ObservableResult(
                        request_id=request.id,
                        values=np.array([10.5, 11.5, 12.5]),
                        units="m",
                        times=observed_dates,
                    )
                    for request in requests
                }

        run_ctx = SimpleNamespace(run=SimpleNamespace(solver="modflow6"))
        monkeypatch.setattr(
            _composite_module,
            "resolve_flow_adapter",
            lambda ctx: (_AlignedAdapter(), run_ctx),
        )

        total, components = metric_fn(ctx, objective="rmse", variable="lake_level")
        assert total == pytest.approx(0.5)
        assert components["cost:rmse@lac0"] == pytest.approx(0.5)

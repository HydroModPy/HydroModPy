"""Tests for the lake-level (LAK stage) calibration target.

Covers the encapsulated feature added to calibrate a MODFLOW 6 LAK lake stage:

- schema: the ``lake`` output support variant and its discrimination,
- extractor: ``extract_lake_series`` reading the LAK obs CSV + JSON sidecar,
- bridge: ``extract_lake`` and the ``lake_id`` threading guard,
- observations: ``load_observed`` mapping ``lake_level`` to the ``lake_levels``
  data family,
- legacy path: the ``variable="lake_level"`` metric extractor, time-aligned.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from hydromodpy.calibration.config import CalibOutputLake, validate_calib_output
from hydromodpy.calibration.metrics import build_metric_extractor
from hydromodpy.calibration.metrics import composite as _composite_module
from hydromodpy.calibration.metrics import solver_extract as _solver_extract_module
from hydromodpy.calibration.metrics.series import load_observed
from hydromodpy.calibration.metrics.solver_extract import extract_lake as _extract_lake
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

    def test_lake_stage_requires_lake_id(self, tmp_path: Path):
        adapter = Modflow6FlowAdapter()
        with pytest.raises(ValueError, match="lake_stage calibration requires lake_id"):
            adapter.extract_calibration_series(self._ctx(tmp_path), None, variable="lake_stage")

    def test_lake_stage_reads_series(self, tmp_path: Path):
        _write_lake_outputs(tmp_path, "m", stages=(86.0, 87.0))
        adapter = Modflow6FlowAdapter()
        series = adapter.extract_calibration_series(
            self._ctx(tmp_path), None, variable="lake_stage", lake_id="lac0"
        )
        assert list(series.values) == pytest.approx([86.0, 87.0])

    def test_lake_volume_reads_the_volume_column(self, tmp_path: Path):
        """The variable suffix selects the LAK state, not just the stage column."""
        _write_lake_outputs(tmp_path, "m", stages=(86.0, 87.0))
        adapter = Modflow6FlowAdapter()
        series = adapter.extract_calibration_series(
            self._ctx(tmp_path), None, variable="lake_volume", lake_id="lac0"
        )
        assert list(series.values) == pytest.approx([86000.0, 87000.0])

    def test_unknown_lake_variable_is_not_implemented(self, tmp_path: Path):
        adapter = Modflow6FlowAdapter()
        with pytest.raises(NotImplementedError, match="lake_inflow"):
            adapter.extract_calibration_series(
                self._ctx(tmp_path), None, variable="lake_inflow", lake_id="lac0"
            )


# ---------------------------------------------------------------------------
# Bridge: extract_lake + lake_id threading guard
# ---------------------------------------------------------------------------


class _LakeAdapter:
    """Stub solver adapter that accepts lake_id and returns a fixed series."""

    def extract_calibration_series(self, ctx, store, *, variable, lake_id=None, time_index=None):
        del ctx, store, variable, time_index
        return pd.Series([1.0, 2.0, 3.0], name=f"stage@{lake_id}")


class _NoLakeAdapter:
    """Stub adapter without lake_id support."""

    def extract_calibration_series(self, ctx, store, *, variable, time_index=None):
        del ctx, store, variable, time_index
        return pd.Series([1.0])


class TestBridge:
    def test_extract_lake_raises_without_flow_run(self):
        ctx = SimpleNamespace(execution=None)
        out = validate_calib_output({"support": "lake", "lake_id": "lac0"})
        with pytest.raises(NotImplementedError, match="No flow solver adapter"):
            _extract_lake(ctx, out)

    def test_extract_lake_slices_last(self, monkeypatch):
        run_ctx = SimpleNamespace(run=SimpleNamespace(solver="modflow6"))
        monkeypatch.setattr(
            _solver_extract_module,
            "resolve_flow_adapter",
            lambda ctx: (_LakeAdapter(), run_ctx),
        )
        out = validate_calib_output(
            {"support": "lake", "lake_id": "lac0", "time": "last", "reducer": "last"}
        )
        assert _extract_lake(SimpleNamespace(), out) == [3.0]

    def test_extract_lake_requires_adapter_lake_support(self, monkeypatch):
        run_ctx = SimpleNamespace(run=SimpleNamespace(solver="modflow_nwt"))
        monkeypatch.setattr(
            _solver_extract_module,
            "resolve_flow_adapter",
            lambda ctx: (_NoLakeAdapter(), run_ctx),
        )
        out = validate_calib_output({"support": "lake", "lake_id": "lac0"})
        with pytest.raises(NotImplementedError, match="cannot extract calibration lake_id"):
            _extract_lake(SimpleNamespace(), out)

    @pytest.mark.parametrize(
        ("declared", "expected_variable"),
        [
            ("stage", "lake_stage"),
            ("volume", "lake_volume"),
            ("surface_area", "lake_surface_area"),
        ],
    )
    def test_declared_quantity_reaches_the_adapter(self, monkeypatch, declared, expected_variable):
        """The config quantity is what the adapter is asked for, not a fixed stage."""
        seen: dict[str, str] = {}

        class _Recorder:
            def extract_calibration_series(
                self, ctx, store, *, variable, lake_id=None, time_index=None
            ):
                del ctx, store, lake_id, time_index
                seen["variable"] = variable
                return pd.Series([1.0])

        run_ctx = SimpleNamespace(run=SimpleNamespace(solver="modflow6"))
        monkeypatch.setattr(
            _solver_extract_module,
            "resolve_flow_adapter",
            lambda ctx: (_Recorder(), run_ctx),
        )
        out = validate_calib_output({"support": "lake", "lake_id": "lac0", "variable": declared})
        _extract_lake(SimpleNamespace(), out)
        assert seen["variable"] == expected_variable


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
# Legacy path: variable="lake_level" metric extractor (time-aligned)
# ---------------------------------------------------------------------------


class TestLegacyLakeLevelPath:
    def test_metric_fn_scores_time_aligned_stage(self, monkeypatch):
        ctx = _lake_levels_ctx()
        metric_fn = build_metric_extractor(
            "lake_level", "rmse", ctx, outputs=None, objective_blocks=None
        )

        observed_dates = pd.DatetimeIndex(["2020-01-01", "2020-01-02", "2020-01-03"])

        class _AlignedAdapter:
            def extract_calibration_series(
                self, ctx, store, *, variable, lake_id=None, time_index=None
            ):
                del ctx, store, variable, lake_id, time_index
                # Observed is [10, 11, 12]; offset by 0.5 -> rmse == 0.5.
                return pd.Series([10.5, 11.5, 12.5], index=observed_dates, name="stage")

        run_ctx = SimpleNamespace(run=SimpleNamespace(solver="modflow6"))
        monkeypatch.setattr(
            _composite_module,
            "resolve_flow_adapter",
            lambda ctx: (_AlignedAdapter(), run_ctx),
        )

        total, components = metric_fn(ctx, objective="rmse", variable="lake_level")
        assert total == pytest.approx(0.5)
        assert components["rmse@lac0"] == pytest.approx(0.5)

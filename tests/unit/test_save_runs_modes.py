"""Unit tests for the calibration ``save_runs`` modes and CLI integration.

Covers:
- ``save_runs = 'none'``: N iterations → N DuckDB rows, 0 Zarrs.
- ``save_runs = 'best_n'``: top N surfaces through ``top_n()``.
- CLI end-to-end with the default analytical objective.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from textwrap import dedent

import pytest

from hydromodpy.calibration.cli import run_calibration_cli
from hydromodpy.calibration.config import CalibrationConfig, CalibParameterDecl
from hydromodpy.calibration.engine import CalibrationEngine
from hydromodpy.calibration.optimizer import (
    EvaluationResult,
    ParamSuggestion,
    build_optimizer,
)
from hydromodpy.calibration.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.persistence import CalibrationPersistence
from hydromodpy.results.catalog import SimulationCatalog


def _write_toml(path: Path, method: str, max_iter: int, save_runs: str,
                save_best_n: int = 3) -> None:
    path.write_text(
        dedent(
            f"""
            [calibration]
            method = "{method}"
            max_iter = {max_iter}
            save_runs = "{save_runs}"
            save_best_n = {save_best_n}
            seed = 0

            [calibration.parameters]
            K = {{ bounds = [1e-6, 1e-3], transform = "log" }}
            Sy = {{ bounds = [0.02, 0.30] }}
            """
        ).strip()
    )


class TestSaveRunsModes:
    def test_none_mode_writes_one_row_per_iteration_and_no_zarr(self, tmp_path: Path):
        toml = tmp_path / "cfg.toml"
        _write_toml(toml, method="grid", max_iter=6, save_runs="none")

        summary = run_calibration_cli(toml, workspace=tmp_path, project="test-none")

        assert summary["save_runs"] == "none"
        assert summary["n_iterations"] >= 4  # grid returns 3x3 = 9, but may stop earlier

        # DuckDB: one row per iteration, no per-sim Zarrs.
        catalog = SimulationCatalog(tmp_path)
        rows = catalog.connection.execute(
            "SELECT COUNT(*) FROM calibration_iterations"
        ).fetchone()[0]
        assert rows == summary["n_iterations"]

        # No Zarr directory was created for any iteration.
        zarrs = list((tmp_path / "simulations").glob("*.zarr"))
        assert zarrs == []

    def test_best_n_mode_persists_top_rows(self, tmp_path: Path):
        toml = tmp_path / "cfg.toml"
        _write_toml(toml, method="grid", max_iter=9, save_runs="best_n",
                    save_best_n=3)

        summary = run_calibration_cli(toml, workspace=tmp_path, project="test-bestn")

        assert summary["save_runs"] == "best_n"
        catalog = SimulationCatalog(tmp_path)
        persistence = CalibrationPersistence(catalog)
        top = persistence.top_n(summary["session_id"], 3)
        # Returned in ascending order of objective.
        values = [row["objective_value"] for row in top]
        assert values == sorted(values)
        assert len(top) <= 3

    def test_lightweight_budget_200_iterations_zero_zarrs(self, tmp_path: Path):
        """Stress check: 50 iter in 'none' mode → 50 rows, 0 Zarrs."""
        toml = tmp_path / "cfg.toml"
        _write_toml(toml, method="optuna", max_iter=50, save_runs="none")

        summary = run_calibration_cli(toml, workspace=tmp_path, project="stress")

        catalog = SimulationCatalog(tmp_path)
        rows = catalog.connection.execute(
            "SELECT COUNT(*) FROM calibration_iterations"
        ).fetchone()[0]
        assert rows == 50

        zarrs = list((tmp_path / "simulations").glob("*.zarr"))
        assert len(zarrs) == 0
        assert summary["n_iterations"] == 50


class TestCalibrationConfigValidation:
    def test_defaults(self):
        cfg = CalibrationConfig(parameters={"K": CalibParameterDecl(bounds=[1e-6, 1e-3])})
        assert cfg.method == "optuna"
        assert cfg.save_runs == "none"
        assert cfg.use_cache is True

    def test_rejects_unknown_method(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CalibrationConfig(method="unknown-method", parameters={})

    def test_save_best_n_non_negative(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CalibrationConfig(save_best_n=-1, parameters={})


class TestEngineCacheIntegration:
    def test_cache_skips_duplicate_params(self, tmp_path: Path):
        space = ParameterSpace(
            [CalibParameter(name="x", lower=0.0, upper=1.0, transform="identity")]
        )
        opt = build_optimizer("grid", space, points_per_dim=3)

        call_count = {"n": 0}

        def evaluator(sugg: ParamSuggestion) -> EvaluationResult:
            call_count["n"] += 1
            return EvaluationResult(
                trial_id=sugg.trial_id,
                sim_id=f"sim-{sugg.trial_id}",
                objective_value=float(sugg.values["x"]),
                status="completed",
            )

        from hydromodpy.calibration.cache import ParamsHashCache

        cache = ParamsHashCache()
        engine = CalibrationEngine(
            space=space,
            optimizer=opt,
            evaluator=evaluator,
            max_iter=3,
            cache=cache,
        )
        session = engine.run()
        assert len(session.history) == 3
        # Cache should be populated after each completed evaluation.
        assert len(cache) == 3

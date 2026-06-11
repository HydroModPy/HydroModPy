"""Tests for simulation/planning/results_config.py - ResultsConfig Pydantic models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.simulation.planning.results_config import (
    BudgetConfig,
    DerivedConfig,
    ResultsConfig,
)


class TestResultsConfigDefaults:
    def test_default_values(self):
        cfg = ResultsConfig()
        assert cfg.persistence.save_catalog is True
        assert cfg.persistence.save_zarr is True
        assert cfg.persistence.save_parquet is True
        assert cfg.persistence.save_lock is True
        assert cfg.keep_solver_files is False
        assert cfg.derived.watertable_elevation is True
        assert cfg.derived.watertable_depth is True
        assert cfg.derived.seepage_areas is True
        assert cfg.budget.spatial_fields is True

    def test_from_dict(self):
        cfg = ResultsConfig.model_validate(
            {
                "persistence": {"save_catalog": True, "save_zarr": False},
                "keep_solver_files": True,
                "derived": {"watertable_depth": False},
            }
        )
        assert cfg.persistence.save_catalog is True
        assert cfg.persistence.save_zarr is False
        assert cfg.keep_solver_files is True
        assert cfg.derived.watertable_depth is False
        assert cfg.derived.watertable_elevation is True

    def test_export_field_rejected(self):
        # [export] is now a top-level section, not nested under results.
        with pytest.raises(ValidationError):
            ResultsConfig.model_validate({"export": {"netcdf": True}})

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            ResultsConfig.model_validate({"unknown_field": True})


class TestDerivedConfig:
    def test_all_false(self):
        cfg = DerivedConfig(
            watertable_elevation=False,
            watertable_depth=False,
            seepage_areas=False,
        )
        dump = cfg.model_dump()
        assert dump["watertable_elevation"] is False
        assert dump["watertable_depth"] is False
        assert dump["seepage_areas"] is False
        assert dump["groundwater_flux"] is False
        assert dump["accumulation_flux"] is True
        assert dump["outflow_drain"] is True
        assert dump["concentration_seepage"] is False
        assert dump["mass_seepage"] is False
        assert dump["mass_accumulated"] is False


class TestIntegrationWithSimulationConfig:
    def test_results_in_simulation_config(self):
        from hydromodpy.simulation.planning.config import SimulationConfig

        cfg = SimulationConfig.model_validate(
            {
                "results": {
                    "persistence": {"save_catalog": True},
                    "keep_solver_files": True,
                    "derived": {"seepage_areas": False},
                },
            }
        )
        assert cfg.results.persistence.save_catalog is True
        assert cfg.results.keep_solver_files is True
        assert cfg.results.derived.seepage_areas is False

    def test_results_default_in_simulation_config(self):
        from hydromodpy.simulation.planning.config import SimulationConfig

        cfg = SimulationConfig()
        assert cfg.results.persistence.save_catalog is True
        assert cfg.results.derived.watertable_depth is True

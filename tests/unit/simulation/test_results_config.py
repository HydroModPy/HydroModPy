"""Tests for simulation/results/config.py - ResultsConfig Pydantic models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.results.config import (
    BudgetConfig,
    DerivedConfig,
    ExportConfig,
    ExportVariablesConfig,
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
        assert cfg.export.netcdf is False
        assert cfg.export.csv_timeseries is True

    def test_from_dict(self):
        cfg = ResultsConfig.model_validate(
            {
                "persistence": {"save_catalog": True, "save_zarr": False},
                "keep_solver_files": True,
                "derived": {"watertable_depth": False},
                "export": {"netcdf": True, "csv_timeseries": True},
            }
        )
        assert cfg.persistence.save_catalog is True
        assert cfg.persistence.save_zarr is False
        assert cfg.keep_solver_files is True
        assert cfg.derived.watertable_depth is False
        assert cfg.derived.watertable_elevation is True
        assert cfg.export.netcdf is True
        assert cfg.export.csv_timeseries is True

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


class TestExportConfig:
    def test_any_enabled_false(self):
        cfg = ExportConfig(netcdf=False, csv_timeseries=False)
        assert cfg.any_enabled() is False

    def test_any_enabled_true(self):
        cfg = ExportConfig(netcdf=True)
        assert cfg.any_enabled() is True

    def test_variables_active_names(self):
        cfg = ExportVariablesConfig(head=True, concentration=True, derived=True)
        names = cfg.active_names()
        assert "head" in names
        assert "concentration" in names
        assert "watertable_depth" in names

    def test_variables_nothing_active(self):
        cfg = ExportVariablesConfig(
            head=False,
            concentration=False,
            budget=False,
            pathlines=False,
            derived=False,
        )
        assert cfg.active_names() == []

    def test_output_dir(self):
        cfg = ExportConfig(output_dir="/tmp/exports")
        assert cfg.output_dir == "/tmp/exports"


class TestIntegrationWithSimulationConfig:
    def test_results_in_simulation_config(self):
        from hydromodpy.simulation.planning.config import SimulationConfig

        cfg = SimulationConfig.model_validate(
            {
                "results": {
                    "persistence": {"save_catalog": True},
                    "keep_solver_files": True,
                    "derived": {"seepage_areas": False},
                    "export": {"netcdf": True},
                },
            }
        )
        assert cfg.results.persistence.save_catalog is True
        assert cfg.results.keep_solver_files is True
        assert cfg.results.derived.seepage_areas is False
        assert cfg.results.export.netcdf is True

    def test_results_default_in_simulation_config(self):
        from hydromodpy.simulation.planning.config import SimulationConfig

        cfg = SimulationConfig()
        assert cfg.results.persistence.save_catalog is True
        assert cfg.results.derived.watertable_depth is True

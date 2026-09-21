"""Tests for the top-level ``[export]`` section (simulation/planning/export_config.py)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.simulation.planning.export_config import ExportConfig


class TestExportConfig:
    def test_defaults(self):
        cfg = ExportConfig()
        assert cfg.csv_timeseries is False
        assert cfg.netcdf is False
        assert cfg.package is False
        assert cfg.time == "last"
        assert cfg.variables == ["head"]

    def test_any_enabled_false(self):
        cfg = ExportConfig(netcdf=False, csv_timeseries=False)
        assert cfg.any_enabled() is False

    def test_any_enabled_true(self):
        cfg = ExportConfig(netcdf=True)
        assert cfg.any_enabled() is True

    def test_package_toggle(self):
        cfg = ExportConfig(package=True)
        assert cfg.package is True

    def test_time_selectors(self):
        assert ExportConfig(time="all").time == "all"
        assert ExportConfig(time="first").time == "first"
        assert ExportConfig(time=3).time == 3
        assert ExportConfig(time=[0, 2, 4]).time == [0, 2, 4]

    def test_time_rejects_garbage(self):
        with pytest.raises(ValidationError):
            ExportConfig(time="middle")

    def test_time_rejects_empty_list(self):
        with pytest.raises(ValidationError):
            ExportConfig(time=[])

    def test_output_dir(self):
        cfg = ExportConfig(output_dir="/tmp/exports")
        assert cfg.output_dir == "/tmp/exports"

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            ExportConfig.model_validate({"unknown": True})

    def test_variables_is_a_flat_list(self):
        cfg = ExportConfig(variables=["head", "release_flux"])
        assert cfg.variables == ["head", "release_flux"]


class TestTopLevelWiring:
    def test_export_is_top_level_on_root_config(self):
        from hydromodpy.config.hydromodpy_config import HydroModPyConfig

        assert "export" in HydroModPyConfig.model_fields
        assert HydroModPyConfig.model_fields["export"].default_factory is ExportConfig

    def test_results_config_has_no_export(self):
        from hydromodpy.simulation.planning.results_config import ResultsConfig

        assert "export" not in ResultsConfig.model_fields

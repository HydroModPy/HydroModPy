"""Tests for the top-level ``[export]`` section (simulation/planning/export_config.py)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.simulation.planning.export_config import (
    ExportConfig,
    ExportVariablesConfig,
)


class TestExportConfig:
    def test_defaults(self):
        cfg = ExportConfig()
        assert cfg.csv_timeseries is True
        assert cfg.netcdf is False
        assert cfg.package is False
        assert cfg.times == "last"

    def test_any_enabled_false(self):
        cfg = ExportConfig(netcdf=False, csv_timeseries=False)
        assert cfg.any_enabled() is False

    def test_any_enabled_true(self):
        cfg = ExportConfig(netcdf=True)
        assert cfg.any_enabled() is True

    def test_package_toggle(self):
        cfg = ExportConfig(package=True)
        assert cfg.package is True

    def test_times_selectors(self):
        assert ExportConfig(times="all").times == "all"
        assert ExportConfig(times="first").times == "first"
        assert ExportConfig(times=3).times == 3
        assert ExportConfig(times=[0, 2, 4]).times == [0, 2, 4]

    def test_times_rejects_garbage(self):
        with pytest.raises(ValidationError):
            ExportConfig(times="middle")

    def test_times_rejects_empty_list(self):
        with pytest.raises(ValidationError):
            ExportConfig(times=[])

    def test_output_dir(self):
        cfg = ExportConfig(output_dir="/tmp/exports")
        assert cfg.output_dir == "/tmp/exports"

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            ExportConfig.model_validate({"unknown": True})


class TestExportVariablesConfig:
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


class TestTopLevelWiring:
    def test_export_is_top_level_on_root_config(self):
        from hydromodpy.config.hydromodpy_config import HydroModPyConfig

        assert "export" in HydroModPyConfig.model_fields
        assert HydroModPyConfig.model_fields["export"].default_factory is ExportConfig

    def test_results_config_has_no_export(self):
        from hydromodpy.simulation.planning.results_config import ResultsConfig

        assert "export" not in ResultsConfig.model_fields

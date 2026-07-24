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
        # Persistence off by default: derived fields recomputed on the
        # fly, budget spatial fields opt-in. Scalars still land in the tables.
        assert cfg.derived.watertable_elevation is False
        assert cfg.derived.watertable_depth is False
        assert cfg.derived.seepage_areas is False
        assert cfg.budget.spatial_fields is False

    def test_from_dict(self):
        cfg = ResultsConfig.model_validate(
            {
                "persistence": {"save_catalog": True, "save_zarr": False},
                "keep_solver_files": True,
                "derived": {"watertable_elevation": True},
            }
        )
        assert cfg.persistence.save_catalog is True
        assert cfg.persistence.save_zarr is False
        assert cfg.keep_solver_files is True
        # Opting one field in leaves the others at their (off) default.
        assert cfg.derived.watertable_elevation is True
        assert cfg.derived.watertable_depth is False

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
        assert dump["accumulation_flux"] is False
        assert dump["outflow_drain"] is False
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
        assert cfg.results.derived.watertable_depth is False


class TestFieldConfigOptionMapping:
    """The field -> option map must stay pinned to the real config fields.

    The map lives in ``results`` (which cannot import ``simulation``), so a
    renamed flag or a new raw budget field would only surface here.
    """

    def test_every_derived_flag_exists_on_derived_config(self):
        from hydromodpy.results.derive.config_flags import DERIVED_FIELD_FLAGS

        unknown = sorted(set(DERIVED_FIELD_FLAGS.values()) - set(DerivedConfig.model_fields))
        assert unknown == []

    def test_every_derived_config_flag_is_mapped(self):
        from hydromodpy.results.derive.config_flags import DERIVED_FIELD_FLAGS

        unmapped = sorted(set(DerivedConfig.model_fields) - set(DERIVED_FIELD_FLAGS.values()))
        assert unmapped == []

    def test_budget_option_exists_on_budget_config(self):
        from hydromodpy.results.derive.config_flags import BUDGET_SPATIAL_OPTION

        section, _, key = BUDGET_SPATIAL_OPTION.partition(".")
        assert section == "budget"
        assert key in BudgetConfig.model_fields

    def test_raw_budget_fields_are_read_from_the_field_registry(self):
        # The list is derived, never written by hand: a new budget/<name>
        # descriptor must become actionable without touching config_flags.
        from hydromodpy.results.derive.config_flags import (
            BUDGET_SPATIAL_OPTION,
            FIELD_CONFIG_OPTIONS,
        )
        from hydromodpy.results.field_registry import FIELD_REGISTRY

        registered = {
            name
            for name, descriptor in FIELD_REGISTRY.items()
            if descriptor.zarr_path.startswith("budget/")
        }
        mapped = {
            name for name, option in FIELD_CONFIG_OPTIONS.items() if option == BUDGET_SPATIAL_OPTION
        }
        assert mapped == registered
        assert {"recharge", "drain"} <= mapped

    def test_seepage_flag_and_field_names_differ(self):
        from hydromodpy.results.derive.config_flags import config_option_for, derived_flag_for

        assert derived_flag_for("seepage_mask") == "seepage_areas"
        assert config_option_for("seepage_mask") == "derived.seepage_areas"
        assert config_option_for("head") is None

    def test_missing_options_separate_an_option_off_from_a_non_applicable_field(self):
        from hydromodpy.results.derive.config_flags import missing_field_options

        class _Run:
            def has_field(self, variable: str) -> bool:
                return variable == "head"

        run = _Run()
        assert missing_field_options(["accumulation_flux", "head"], run) == [
            "derived.accumulation_flux"
        ]
        # A missing field no option controls stays a quiet skip.
        assert missing_field_options(["lake_stage"], run) == []

    def test_dropped_raw_budget_field_is_actionable(self):
        # A run whose intermediate per-cell budget was dropped no longer holds
        # 'recharge'. Rendering it again needs a new solve, and the option to
        # set for that must be named.
        from hydromodpy.results.derive.config_flags import missing_field_options

        class _Run:
            def has_field(self, variable: str) -> bool:
                return variable == "head"

        assert missing_field_options(["recharge"], _Run()) == ["budget.spatial_fields"]

    def test_log_missing_field_warns_only_for_an_option_controlled_field(self):
        import logging

        from hydromodpy.results.derive.config_flags import log_missing_field

        class _Run:
            def has_field(self, variable: str) -> bool:
                return False

        records: list[tuple[int, str]] = []

        class _Logger:
            def warning(self, msg, *args):
                records.append((logging.WARNING, msg % args))

            def debug(self, msg, *args):
                records.append((logging.DEBUG, msg % args))

        log_missing_field(_Logger(), _Run(), "accumulation_flux", "metrics for run x")
        log_missing_field(_Logger(), _Run(), "recharge", "metrics for run x")
        log_missing_field(_Logger(), _Run(), "lake_stage", "metrics for run x")

        assert records[0][0] == logging.WARNING
        assert "[simulation.results.derived] accumulation_flux = true" in records[0][1]
        assert records[1][0] == logging.WARNING
        assert "[simulation.results.budget] spatial_fields = true" in records[1][1]
        assert records[2][0] == logging.DEBUG

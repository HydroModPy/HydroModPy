"""Tests for simulation/planning/results_config.py - ResultsConfig Pydantic models."""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from hydromodpy.simulation.planning.results_config import ResultsConfig


class TestResultsConfigDefaults:
    def test_default_values(self):
        cfg = ResultsConfig()
        assert cfg.persistence.save_catalog is True
        assert cfg.persistence.save_zarr is True
        assert cfg.persistence.save_parquet is True
        assert cfg.keep_solver_files is False
        assert cfg.keep_per_cell_budget is True

    def test_from_dict(self):
        cfg = ResultsConfig.model_validate(
            {
                "persistence": {"save_catalog": True, "save_zarr": False},
                "keep_solver_files": True,
            }
        )
        assert cfg.persistence.save_catalog is True
        assert cfg.persistence.save_zarr is False
        assert cfg.keep_solver_files is True

    def test_export_field_rejected(self):
        # [export] is now a top-level section, not nested under results.
        with pytest.raises(ValidationError):
            ResultsConfig.model_validate({"export": {"netcdf": True}})

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            ResultsConfig.model_validate({"unknown_field": True})

    @pytest.mark.parametrize("retired", ["derived", "budget"])
    def test_a_retired_table_is_refused(self, retired):
        # The migrations drop these tables from a file or a stored config; the
        # model itself knows neither.
        with pytest.raises(ValidationError):
            ResultsConfig.model_validate({retired: {}})
        assert retired not in ResultsConfig.model_fields


class TestKeepPerCellBudget:
    def test_on_by_default(self):
        assert ResultsConfig().keep_per_cell_budget is True

    def test_can_be_turned_off(self):
        cfg = ResultsConfig.model_validate({"keep_per_cell_budget": False})
        assert cfg.keep_per_cell_budget is False

    def test_is_a_dev_boolean(self):
        from hydromodpy.core.config_kit.profile import Profile

        field = ResultsConfig.model_fields["keep_per_cell_budget"]
        assert field.annotation is bool
        assert Profile.DEV in field.metadata
        assert field.is_required() is False

    def test_a_non_boolean_is_refused(self):
        with pytest.raises(ValidationError):
            ResultsConfig.model_validate({"keep_per_cell_budget": "maybe"})

    def test_a_misspelled_sibling_is_refused(self):
        with pytest.raises(ValidationError):
            ResultsConfig.model_validate({"keep_per_cell_budgets": True})

    def test_the_description_names_no_example_project(self):
        text = ResultsConfig.model_fields["keep_per_cell_budget"].description.lower()
        projects = Path(__file__).resolve().parents[3] / "examples" / "projects"
        names = sorted(folder.name.lower() for folder in projects.iterdir() if folder.is_dir())
        assert names
        for name in names:
            assert name not in text
            bare = re.sub(r"^\d+_", "", name)
            # A one-word folder ("calibration") is also plain prose.
            if "_" in bare:
                assert bare not in text


class TestIntegrationWithSimulationConfig:
    def test_results_in_simulation_config(self):
        from hydromodpy.simulation.planning.config import SimulationConfig

        cfg = SimulationConfig.model_validate(
            {
                "results": {
                    "persistence": {"save_catalog": True},
                    "keep_solver_files": True,
                },
            }
        )
        assert cfg.results.persistence.save_catalog is True
        assert cfg.results.keep_solver_files is True

    def test_results_default_in_simulation_config(self):
        from hydromodpy.simulation.planning.config import SimulationConfig

        cfg = SimulationConfig()
        assert cfg.results.persistence.save_catalog is True
        assert cfg.results.keep_per_cell_budget is True


def _run(*, terms: dict[str, tuple[str, ...]] | None = None, present=("head",), head=True):
    """A run whose store declares what its ``budget/`` group kept.

    ``terms`` maps a policy to the terms it kept; None leaves the group without
    attributes, as a store written before they existed. ``head=False`` leaves
    the head out, as a lumped model does.
    """
    import numpy as np
    import zarr

    root = zarr.group()
    if head:
        root.create_array("head", data=np.zeros((2, 1, 3)))
    budget = root.create_group("budget")
    if terms is not None:
        ((policy, kept),) = terms.items()
        budget.attrs.update({"policy": policy, "kept_terms": list(kept)})
    store = SimpleNamespace(root=root, close=lambda: None)
    return SimpleNamespace(
        sim_id="sim-x",
        has_field=lambda variable, **_: variable in present,
        _catalog=SimpleNamespace(open_zarr=lambda sim_id: store),
    )


class TestWhatTheRunKeptDecidesTheMessage:
    """A missing field is actionable only when the run did not keep what it reads."""

    def test_the_only_option_is_the_budget_switch(self):
        from hydromodpy.results.derive.config_flags import KEEP_BUDGET_OPTION, config_option_for

        assert KEEP_BUDGET_OPTION == "keep_per_cell_budget"
        assert KEEP_BUDGET_OPTION in ResultsConfig.model_fields
        for field in ("release_flux", "accumulation_flux", "seepage_mask", "recharge", "drain"):
            assert config_option_for(field) == KEEP_BUDGET_OPTION
        # A head or a static parameter reads no budget term: no option keeps it.
        assert config_option_for("head") is None
        assert config_option_for("lake_stage") is None

    def test_every_raw_budget_field_of_the_registry_has_the_option(self):
        from hydromodpy.core.budget_terms import PER_CELL_BUDGET_TERMS
        from hydromodpy.results.derive.config_flags import KEEP_BUDGET_OPTION, config_option_for
        from hydromodpy.results.field_registry import FIELD_REGISTRY

        registered = {
            name
            for name, descriptor in FIELD_REGISTRY.items()
            if descriptor.zarr_path.startswith("budget/")
        }
        assert registered
        assert {name for name in registered if config_option_for(name) == KEEP_BUDGET_OPTION} == (
            registered & PER_CELL_BUDGET_TERMS
        )

    def test_a_consumers_run_that_left_a_term_out_is_actionable(self):
        from hydromodpy.results.derive.config_flags import (
            missing_field_explanation,
            missing_field_options,
        )

        run = _run(terms={"consumers": ("drain",)})

        assert missing_field_options(["release_flux", "head"], run) == ["keep_per_cell_budget"]
        text = missing_field_explanation(["release_flux"], run)
        assert "kept only the per-cell budget terms its consumers read (drain)" in text
        assert "recharge" in text
        assert "stream" in text
        assert "drain," not in text.split("also needs")[1]
        assert "[[export]]" in text
        assert "[simulation.results] keep_per_cell_budget = true" in text
        assert "run the simulation again" in text

    def test_a_consumers_run_that_kept_everything_the_field_reads_is_quiet(self):
        # The terms are kept and no array is there: the model does not produce them.
        from hydromodpy.core.budget_terms import budget_terms_for
        from hydromodpy.results.derive.config_flags import (
            missing_field_explanation,
            missing_field_options,
        )

        run = _run(terms={"consumers": budget_terms_for("release_flux")})

        assert missing_field_options(["release_flux"], run) == []
        assert missing_field_explanation(["release_flux"], run) == ""

    def test_a_run_that_kept_the_whole_budget_is_quiet(self):
        from hydromodpy.results.derive.config_flags import missing_field_options

        run = _run(terms={"all": ("drain",)})

        assert missing_field_options(["release_flux", "recharge"], run) == []

    def test_a_store_without_attributes_was_written_before_the_budget_was_kept(self):
        from hydromodpy.results.derive.config_flags import (
            missing_field_explanation,
            missing_field_options,
        )

        run = _run(terms=None)

        assert missing_field_options(["accumulation_flux"], run) == ["keep_per_cell_budget"]
        text = missing_field_explanation(["accumulation_flux"], run)
        assert "written before the per-cell budget was kept by default" in text
        assert "run the simulation again" in text

    def test_a_store_without_attributes_and_without_head_is_quiet(self):
        # A lumped run (GR4J) writes no budget group and no head: no run can fix that.
        from hydromodpy.results.derive.config_flags import (
            missing_field_explanation,
            missing_field_options,
        )

        run = _run(terms=None, head=False)

        assert missing_field_options(["release_flux"], run) == []
        assert missing_field_explanation(["release_flux"], run) == ""

    def test_a_field_that_is_present_or_reads_no_term_is_never_actionable(self):
        from hydromodpy.results.derive.config_flags import missing_field_options

        run = _run(terms={"consumers": ()}, present=("head", "release_flux"))

        assert missing_field_options(["release_flux", "head", "lake_stage"], run) == []

    def test_log_missing_field_warns_only_when_the_run_could_have_kept_the_field(self):
        import logging

        from hydromodpy.results.derive.config_flags import log_missing_field

        records: list[tuple[int, str]] = []

        class _Logger:
            def warning(self, msg, *args):
                records.append((logging.WARNING, msg % args))

            def debug(self, msg, *args):
                records.append((logging.DEBUG, msg % args))

        consumers = _run(terms={"consumers": ("drain",)})
        log_missing_field(_Logger(), consumers, "recharge", "metrics for run x")
        log_missing_field(_Logger(), _run(terms={"all": ("drain",)}), "recharge", "metrics")
        log_missing_field(_Logger(), consumers, "lake_stage", "metrics for run x")

        assert records[0][0] == logging.WARNING
        assert "kept only the per-cell budget terms its consumers read (drain)" in records[0][1]
        assert records[1][0] == logging.DEBUG
        assert records[2][0] == logging.DEBUG

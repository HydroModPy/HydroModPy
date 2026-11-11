"""Tests for solver/base/results_config.py - ResultsConfig Pydantic models."""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from hydromodpy.solver.base.results_config import ResultsConfig


class TestResultsConfigDefaults:
    def test_default_values(self):
        cfg = ResultsConfig()
        assert cfg.persistence.save_catalog is True
        assert cfg.persistence.save_zarr is True
        assert cfg.persistence.save_parquet is True
        assert cfg.keep_solver_files is False
        assert cfg.keep_face_flows is False
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


class TestKeepFaceFlows:
    def test_off_by_default(self):
        assert ResultsConfig().keep_face_flows is False

    def test_can_be_turned_on(self):
        cfg = ResultsConfig.model_validate({"keep_face_flows": True})
        assert cfg.keep_face_flows is True

    def test_is_a_user_boolean(self):
        from hydromodpy.core.config_kit.profile import Profile

        field = ResultsConfig.model_fields["keep_face_flows"]
        assert field.annotation is bool
        assert Profile.USER in field.metadata
        assert field.is_required() is False

    def test_a_non_boolean_is_refused(self):
        with pytest.raises(ValidationError):
            ResultsConfig.model_validate({"keep_face_flows": "yes"})

    def test_the_description_names_the_two_solvers_and_what_it_weighs(self):
        text = ResultsConfig.model_fields["keep_face_flows"].description
        assert "MODFLOW 6 and MODFLOW-NWT" in text
        assert "about 350 MB in float32" in text
        assert "A kept calibration trial never keeps it." in text

    def test_the_description_passes_the_documentation_gates(self):
        from tools.docs import field_registry

        nodes = [
            node
            for path, node in field_registry.build().items()
            if path.endswith(".keep_face_flows")
        ]
        assert nodes
        assert field_registry.gate_hits(nodes[0]) == []


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
        projects = Path(__file__).resolve().parents[4] / "examples" / "projects"
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
        from hydromodpy.solver.base.simulation_config import SimulationConfig

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
        from hydromodpy.solver.base.simulation_config import SimulationConfig

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
        from hydromodpy.core.budget.terms import budget_terms_for
        from hydromodpy.results.derive.config_flags import KEEP_BUDGET_OPTION

        assert KEEP_BUDGET_OPTION == "keep_per_cell_budget"
        assert KEEP_BUDGET_OPTION in ResultsConfig.model_fields
        for field in (
            "release_flux",
            "drain_accumulation_flux",
            "seepage_mask",
            "recharge",
            "drain",
        ):
            assert budget_terms_for(field)
        # A head or a static parameter reads no budget term: no option keeps it.
        assert not budget_terms_for("head")
        assert not budget_terms_for("lake_stage")

    def test_every_raw_budget_field_of_the_registry_has_the_option(self):
        from hydromodpy.core.budget.terms import PER_CELL_BUDGET_TERMS, budget_terms_for
        from hydromodpy.results.field_registry import FIELD_REGISTRY

        registered = {
            name
            for name, descriptor in FIELD_REGISTRY.items()
            if descriptor.zarr_path.startswith("budget/")
        }
        assert registered
        assert {name for name in registered if budget_terms_for(name)} == (
            registered & PER_CELL_BUDGET_TERMS
        )

    def test_a_consumers_run_that_left_a_term_out_is_actionable(self):
        from hydromodpy.results.derive.config_flags import (
            diagnose_missing,
            missing_field_explanation,
        )

        run = _run(terms={"consumers": ("drain",)})

        assert diagnose_missing(["release_flux", "head"], run) is not None
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
        from hydromodpy.core.budget.terms import budget_terms_for
        from hydromodpy.results.derive.config_flags import (
            diagnose_missing,
            missing_field_explanation,
        )

        run = _run(terms={"consumers": budget_terms_for("release_flux")})

        assert diagnose_missing(["release_flux"], run) is None
        assert missing_field_explanation(["release_flux"], run) == ""

    def test_a_run_that_kept_the_whole_budget_is_quiet(self):
        from hydromodpy.results.derive.config_flags import diagnose_missing

        run = _run(terms={"all": ("drain",)})

        assert diagnose_missing(["release_flux", "recharge"], run) is None

    def test_a_store_without_attributes_was_written_before_the_budget_was_kept(self):
        from hydromodpy.results.derive.config_flags import (
            diagnose_missing,
            missing_field_explanation,
        )

        run = _run(terms=None)

        assert diagnose_missing(["drain_accumulation_flux"], run) is not None
        text = missing_field_explanation(["drain_accumulation_flux"], run)
        assert "written before the per-cell budget was kept by default" in text
        assert "run the simulation again" in text

    def test_a_store_without_attributes_and_without_head_is_quiet(self):
        # A lumped run (GR4J) writes no budget group and no head: no run can fix that.
        from hydromodpy.results.derive.config_flags import (
            diagnose_missing,
            missing_field_explanation,
        )

        run = _run(terms=None, head=False)

        assert diagnose_missing(["release_flux"], run) is None
        assert missing_field_explanation(["release_flux"], run) == ""

    def test_a_field_that_is_present_or_reads_no_term_is_never_actionable(self):
        from hydromodpy.results.derive.config_flags import diagnose_missing

        run = _run(terms={"consumers": ()}, present=("head", "release_flux"))

        assert diagnose_missing(["release_flux", "head", "lake_stage"], run) is None

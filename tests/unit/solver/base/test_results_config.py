"""Tests for solver/base/results_config.py - ResultsConfig Pydantic models."""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from hydromodpy.solver.base.results_config import ResultsConfig


class TestKeepFaceFlows:
    def test_is_a_user_boolean(self):
        from hydromodpy.core.config_kit.profile import Profile

        field = ResultsConfig.model_fields["keep_face_flows"]
        assert field.annotation is bool
        assert Profile.USER in field.metadata
        assert field.is_required() is False

    def test_the_description_names_the_two_solvers_and_what_it_weighs(self):
        text = ResultsConfig.model_fields["keep_face_flows"].description
        assert "MODFLOW 6 and MODFLOW-NWT" in text
        assert "about 350 MB in float32" in text
        assert "A kept calibration trial never keeps it." in text


class TestKeepPerCellBudget:
    def test_is_a_dev_boolean(self):
        from hydromodpy.core.config_kit.profile import Profile

        field = ResultsConfig.model_fields["keep_per_cell_budget"]
        assert field.annotation is bool
        assert Profile.DEV in field.metadata
        assert field.is_required() is False

    def test_a_non_boolean_is_refused(self):
        with pytest.raises(ValidationError):
            ResultsConfig.model_validate({"keep_per_cell_budget": "maybe"})

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

"""``[results]`` switches that keep the per-cell flows and budget of a run.

``keep_face_flows`` is a user switch and ``keep_per_cell_budget`` a developer one.
A field a run cannot give is explained from what its store kept, so the message
only names an option when the run really lacked what the field reads.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import zarr
from pydantic import ValidationError

from hydromodpy.core.budget.terms import PER_CELL_BUDGET_TERMS, budget_terms_for
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.results.derive.config_flags import (
    KEEP_BUDGET_OPTION,
    diagnose_missing,
    missing_field_explanation,
)
from hydromodpy.results.field_registry import FIELD_REGISTRY
from hydromodpy.solver.base.results_config import ResultsConfig

FIELDS = ResultsConfig.model_fields


def run_that_kept(*, terms: dict[str, tuple[str, ...]] | None):
    """A run whose store declares what its ``budget/`` group kept.

    ``terms`` maps a policy to the terms it kept. None leaves the group without
    attributes, as a store written before they existed.
    """
    root = zarr.group()
    root.create_array("head", data=np.zeros((2, 1, 3)))
    budget = root.create_group("budget")
    if terms is not None:
        ((policy, kept),) = terms.items()
        budget.attrs.update({"policy": policy, "kept_terms": list(kept)})
    store = SimpleNamespace(root=root, close=lambda: None)
    return SimpleNamespace(
        sim_id="sim-x",
        has_field=lambda variable, **_: variable == "head",
        _catalog=SimpleNamespace(open_zarr=lambda sim_id: store),
    )


SWITCHES = [
    pytest.param("keep_face_flows", Profile.USER, id="face flows"),
    pytest.param("keep_per_cell_budget", Profile.DEV, id="per-cell budget"),
]


@pytest.mark.parametrize(("name", "profile"), SWITCHES)
def test_switch_is_an_optional_boolean_of_its_profile(name: str, profile: Profile) -> None:
    field = FIELDS[name]

    assert field.annotation is bool
    assert profile in field.metadata
    assert field.is_required() is False


def test_face_flows_description() -> None:
    text = FIELDS["keep_face_flows"].description

    assert "MODFLOW 6 and MODFLOW-NWT" in text
    assert "about 350 MB in float32" in text
    assert "A kept calibration trial never keeps it." in text


def test_non_boolean_budget_switch_is_refused() -> None:
    with pytest.raises(ValidationError):
        ResultsConfig.model_validate({"keep_per_cell_budget": "maybe"})


def test_budget_description_names_no_example_project() -> None:
    text = FIELDS["keep_per_cell_budget"].description.lower()
    projects = Path(__file__).resolve().parents[4] / "examples" / "projects"
    names = sorted(folder.name.lower() for folder in projects.iterdir() if folder.is_dir())
    assert names
    for name in names:
        assert name not in text
        bare = re.sub(r"^\d+_", "", name)
        # A one-word folder ("calibration") is also plain prose.
        if "_" in bare:
            assert bare not in text


def test_budget_switch_is_the_only_option_that_keeps_a_budget_field() -> None:
    assert KEEP_BUDGET_OPTION == "keep_per_cell_budget"
    assert KEEP_BUDGET_OPTION in FIELDS
    for field in ("release_flux", "drain_accumulation_flux", "seepage_mask", "recharge", "drain"):
        assert budget_terms_for(field)
    # A head or a static parameter reads no budget term: no option keeps it.
    assert not budget_terms_for("head")
    assert not budget_terms_for("lake_stage")


def test_every_raw_budget_field_has_the_option() -> None:
    registered = {
        name
        for name, descriptor in FIELD_REGISTRY.items()
        if descriptor.zarr_path.startswith("budget/")
    }
    assert registered
    assert {name for name in registered if budget_terms_for(name)} == (
        registered & PER_CELL_BUDGET_TERMS
    )


def test_run_that_kept_what_the_field_reads_is_quiet() -> None:
    # The terms are kept and no array is there: the model does not produce them.
    run = run_that_kept(terms={"consumers": budget_terms_for("release_flux")})

    assert diagnose_missing(["release_flux"], run) is None
    assert missing_field_explanation(["release_flux"], run) == ""


def test_run_that_kept_the_whole_budget_is_quiet() -> None:
    run = run_that_kept(terms={"all": ("drain",)})

    assert diagnose_missing(["release_flux", "recharge"], run) is None


def test_store_without_attributes_predates_the_kept_budget() -> None:
    run = run_that_kept(terms=None)

    assert diagnose_missing(["drain_accumulation_flux"], run) is not None
    text = missing_field_explanation(["drain_accumulation_flux"], run)
    assert "written before the per-cell budget was kept by default" in text
    assert "run the simulation again" in text

"""A store that kept only some terms of a multi-term field does not serve it.

Under the ``"consumers"`` policy a field is available only when every term it
reads is declared kept. A term declared with no array is a term the model does
not produce, which is fine. Under ``"all"`` nothing changes.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.core.budget_terms import BudgetKeep, budget_terms_for
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.derive.config_flags import diagnose_missing, missing_field_explanation
from hydromodpy.results.derive.virtual_fields import (
    available_virtual_fields,
    read_field_or_virtual,
    read_field_range_or_virtual,
)
from hydromodpy.results.errors import FieldNotFoundError
from hydromodpy.results.run import Run

N_STEPS = 4
N_CELLS = 3


@pytest.fixture
def catalog(tmp_path: Path):
    with Catalog(tmp_path / "workspace") as cat:
        yield cat


def _seed(catalog: Catalog, keep: BudgetKeep | None, written: tuple[str, ...]) -> str:
    sid = str(uuid.uuid4())
    reg = catalog.register_simulation(
        sid, project="p", solver="modflow6", n_cells=N_CELLS, n_layers=1, n_timesteps=N_STEPS
    )
    reg.zarr.close()
    rng = np.random.default_rng(3)
    sz = catalog.open_zarr(sid)
    try:
        sz.write_field_stack("head", np.full((N_STEPS, 1, N_CELLS), 10.0))
        for name in written:
            sz.write_field_stack(
                name, -rng.uniform(0.0, 1e-3, (N_STEPS, 1, N_CELLS)), subgroup="budget"
            )
        if keep is not None:
            sz.write_budget_policy(keep, written)
    finally:
        sz.close()
    return sid


def test_a_consumers_store_with_the_drain_only_refuses_the_release_flux(catalog) -> None:
    keep = BudgetKeep.of_terms({"drain", "drain_to_mover"})
    sid = _seed(catalog, keep, ("drain",))

    sz = catalog.open_zarr(sid)
    try:
        assert "release_flux" not in available_virtual_fields(sz.root)
        assert "outflow_drain" in available_virtual_fields(sz.root)
    finally:
        sz.close()
    run = Run(sid, catalog)
    assert not run.has_field("release_flux")
    assert "release_flux" not in run.array.list_fields()
    with pytest.raises(FieldNotFoundError):
        run.field("release_flux", timestep=0)
    with pytest.raises(KeyError):
        read_field_or_virtual(catalog, sid, "release_flux", 0)
    with pytest.raises(KeyError):
        read_field_range_or_virtual(catalog, sid, "release_flux", 0, N_STEPS)


def test_the_diagnosis_names_the_release_terms_the_store_lacks(catalog) -> None:
    sid = _seed(catalog, BudgetKeep.of_terms({"drain", "drain_to_mover"}), ("drain",))
    run = Run(sid, catalog)

    problem = diagnose_missing(["release_flux"], run)
    text = missing_field_explanation(["release_flux"], run)

    assert problem is not None
    assert {"stream", "lake", "recharge"} <= set(problem.terms)
    assert "drain" not in problem.terms
    assert "stream" in text and "lake" in text
    assert "keep_per_cell_budget" in text


def test_a_consumers_store_that_declares_every_release_term_serves_the_field(catalog) -> None:
    keep = BudgetKeep.of_terms(budget_terms_for("release_flux"))
    sid = _seed(catalog, keep, ("drain", "recharge"))
    run = Run(sid, catalog)

    assert run.has_field("release_flux")
    rows = read_field_range_or_virtual(catalog, sid, "release_flux", 0, N_STEPS)
    assert rows.shape == (N_STEPS, N_CELLS)
    assert diagnose_missing(["release_flux"], run) is None


def test_the_all_policy_serves_the_field_from_the_drain_alone(catalog) -> None:
    sid = _seed(catalog, BudgetKeep.everything(), ("drain",))

    assert Run(sid, catalog).has_field("release_flux")


def test_a_store_without_attributes_serves_the_field_from_the_drain_alone(catalog) -> None:
    sid = _seed(catalog, None, ("drain",))

    assert Run(sid, catalog).has_field("release_flux")

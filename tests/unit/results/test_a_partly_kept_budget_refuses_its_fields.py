"""A store that kept only some terms of a multi-term field does not serve it.

Under the ``"consumers"`` policy a field is available only when every term it
reads is declared kept. A term declared with no array is a term the model does
not produce, which is fine. Under ``"all"`` nothing changes.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.core.budget_terms import BudgetKeep, budget_terms_for
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.derive.config_flags import diagnose_missing, missing_field_explanation
from hydromodpy.results.derive.virtual_fields import (
    available_virtual_fields,
    read_field_or_virtual,
    read_field_range_or_virtual,
)
from hydromodpy.results.errors import FieldNotFoundError
from hydromodpy.results.run import Run
from hydromodpy.results.storage.sealing import seal_completed
from tests._helpers.run_stores import open_run_store

N_STEPS = 4
N_CELLS = 3


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return tmp_path / "workspace"


@contextmanager
def _sealed(
    project: Path, keep: BudgetKeep | None, written: tuple[str, ...]
) -> Iterator[tuple[Catalog, str]]:
    """Seal a run that wrote the *written* terms under *keep*; yield the catalog and its id."""
    store = open_run_store(project, "run", n_cells=N_CELLS, n_layers=1, n_timesteps=N_STEPS)
    sid = store.sim_id
    rng = np.random.default_rng(3)
    sz = store.open_zarr(sid)
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
    seal_completed(store)
    rebuild_index(project)
    with Catalog(project) as catalog:
        yield catalog, sid


def test_a_consumers_store_with_the_drain_only_refuses_the_release_flux(project) -> None:
    keep = BudgetKeep.of_terms({"drain", "drain_to_mover"})
    with _sealed(project, keep, ("drain",)) as (catalog, sid):
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
            run.field("release_flux", time=0)
        with pytest.raises(KeyError):
            read_field_or_virtual(catalog, sid, "release_flux", 0)
        with pytest.raises(KeyError):
            read_field_range_or_virtual(catalog, sid, "release_flux", 0, N_STEPS)


def test_the_diagnosis_names_the_release_terms_the_store_lacks(project) -> None:
    keep = BudgetKeep.of_terms({"drain", "drain_to_mover"})
    with _sealed(project, keep, ("drain",)) as (catalog, sid):
        run = Run(sid, catalog)

        problem = diagnose_missing(["release_flux"], run)
        text = missing_field_explanation(["release_flux"], run)

        assert problem is not None
        assert {"stream", "lake", "recharge"} <= set(problem.terms)
        assert "drain" not in problem.terms
        assert "stream" in text and "lake" in text
        assert "keep_per_cell_budget" in text


def test_a_consumers_store_that_declares_every_release_term_serves_the_field(project) -> None:
    keep = BudgetKeep.of_terms(budget_terms_for("release_flux"))
    with _sealed(project, keep, ("drain", "recharge")) as (catalog, sid):
        run = Run(sid, catalog)

        assert run.has_field("release_flux")
        rows = read_field_range_or_virtual(catalog, sid, "release_flux", 0, N_STEPS)
        assert rows.shape == (N_STEPS, N_CELLS)
        assert diagnose_missing(["release_flux"], run) is None


def test_the_all_policy_serves_the_field_from_the_drain_alone(project) -> None:
    with _sealed(project, BudgetKeep.everything(), ("drain",)) as (catalog, sid):
        assert Run(sid, catalog).has_field("release_flux")


def test_a_store_without_attributes_serves_the_field_from_the_drain_alone(project) -> None:
    with _sealed(project, None, ("drain",)) as (catalog, sid):
        assert Run(sid, catalog).has_field("release_flux")

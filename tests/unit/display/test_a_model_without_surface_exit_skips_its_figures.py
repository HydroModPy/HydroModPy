"""A figure built on the surface outflow is skipped on a model without exit.

A model with no drain, stream, lake or surface excess releases no groundwater
at the surface, so ``release_flux`` does not exist. The field is rebuilt on
read, so nothing stops the run: the figure is skipped with that reason, and
the skip is not actionable, since no option adds an exit to the model.

That holds only when the store proves it: a run that kept the whole budget, or
every exit term with no array. A run that kept the terms its consumers read
(``consumers``) may lack the exits because the plan never asked for them, and
its skip names ``keep_per_cell_budget``.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.core.budget_terms import budget_terms_for
from hydromodpy.display import runs
from hydromodpy.display.config import DisplayConfig
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.run import Run
from hydromodpy.results.storage.sealing import seal_completed
from hydromodpy.results.zarr_store import SimulationZarr
from tests._helpers.run_stores import open_run_store

N_STEPS = 2
N_CELLS = 4


def _seed(
    project: Path,
    budget: dict[str, np.ndarray],
    *,
    policy: str = "all",
    kept_terms: list[str] | None = None,
    edit: Callable[[SimulationZarr], None] | None = None,
) -> str:
    """Write one run with a head and the budget terms given, seal it and return its id.

    ``edit`` changes the field store after the writes, before the seal.
    """
    store = open_run_store(
        project, f"run_{uuid.uuid4().hex[:8]}", n_cells=N_CELLS, n_layers=1, n_timesteps=N_STEPS
    )
    sid = store.sim_id
    sz = store.open_zarr(sid)
    try:
        sz.write_field_stack("head", np.full((N_STEPS, 1, N_CELLS), 120.0))
        for name, values in budget.items():
            sz.write_field_stack(name, values, subgroup="budget")
        if budget:
            # What the extractor declares: the names written under "all", the
            # plan's terms, produced or not, under "consumers".
            terms = sorted(budget) if kept_terms is None else sorted(kept_terms)
            sz.root["budget"].attrs.update({"policy": policy, "kept_terms": terms})
        if edit is not None:
            edit(sz)
    finally:
        sz.close()
    seal_completed(store)
    return sid


def _recharge_only() -> dict[str, np.ndarray]:
    return {"recharge": np.full((N_STEPS, 1, N_CELLS), 1e-5)}


@pytest.fixture
def seeded(tmp_path: Path) -> Iterator[Callable[..., Run]]:
    """Seal a run, index the project and return the run read through the index."""
    project = tmp_path / "p"
    readers: list[Catalog] = []

    def _open(budget: dict[str, np.ndarray], **options: object) -> Run:
        sid = _seed(project, budget, **options)
        rebuild_index(project)
        reader = Catalog(project)
        readers.append(reader)
        return Run(sid, reader)

    yield _open
    for reader in readers:
        reader.close()


def test_a_run_without_an_exit_does_not_serve_the_release_flux(seeded) -> None:
    assert not seeded(_recharge_only()).has_field("release_flux")


def test_the_figure_is_skipped_with_the_physical_reason(seeded, tmp_path, caplog) -> None:
    run = seeded(_recharge_only())
    cfg = DisplayConfig(figures=["downslope_distance_map"], save=False)

    with caplog.at_level(logging.DEBUG, logger="hydromodpy.display.runs"):
        report = runs.render_figures_for_run(run, cfg, output_dir=tmp_path / "figures")

    assert report.rendered == ()
    (skip,) = report.skipped
    assert skip.name == "downslope_distance_map"
    assert "no drain, stream, lake or surface excess" in skip.reason
    assert "release_flux" in skip.reason
    # No results option can add an exit to the model: the skip is not actionable.
    assert not skip.actionable
    assert "keep_per_cell_budget" not in caplog.text


def test_a_drain_only_figure_names_the_drain(seeded) -> None:
    run = seeded(_recharge_only())

    reason = runs.unavailable_reason(runs._get_figure("accumulation_map"), run)

    assert reason is not None
    assert "the model has no drain," in reason
    assert "accumulation_flux" in reason


def test_a_model_with_a_drain_keeps_the_figure_reason(seeded) -> None:
    budget = _recharge_only()
    budget["drain"] = np.full((N_STEPS, 1, N_CELLS), -1e-4)
    run = seeded(budget)

    assert run.has_field("release_flux")
    assert (
        runs._no_surface_exit_reason(run, runs._get_figure("downslope_distance_map").spec) is None
    )


def test_a_run_without_budget_is_not_judged(seeded) -> None:
    run = seeded({})

    spec = runs._get_figure("downslope_distance_map").spec
    assert runs._no_surface_exit_reason(run, spec) is None


def test_a_store_without_attributes_keeps_the_old_reading(seeded) -> None:

    def _drop_attributes(sz: SimulationZarr) -> None:
        for key in ("policy", "kept_terms"):
            del sz.root["budget"].attrs[key]

    run = seeded(_recharge_only(), edit=_drop_attributes)

    spec = runs._get_figure("downslope_distance_map").spec
    assert "no drain, stream, lake or surface excess" in runs._no_surface_exit_reason(run, spec)


def test_a_consumers_run_that_never_kept_the_exits_is_not_a_model_without_exit(
    seeded, tmp_path, caplog
) -> None:
    run = seeded(_recharge_only(), policy="consumers", kept_terms=["recharge"])
    cfg = DisplayConfig(figures=["downslope_distance_map"], save=False)

    spec = runs._get_figure("downslope_distance_map").spec
    assert runs._no_surface_exit_reason(run, spec) is None
    with caplog.at_level(logging.DEBUG, logger="hydromodpy.display.runs"):
        report = runs.render_figures_for_run(run, cfg, output_dir=tmp_path / "figures")

    (skip,) = report.skipped
    assert "the model has no" not in skip.reason
    assert skip.actionable
    (record,) = [r for r in caplog.records if "downslope_distance_map" in r.getMessage()]
    assert record.levelno == logging.WARNING
    message = record.getMessage()
    assert "kept only the per-cell budget terms its consumers read (recharge)" in message
    assert "[simulation.results] keep_per_cell_budget = true" in message
    assert "spatial_fields" not in message


def test_a_consumers_run_that_kept_the_exits_without_array_has_no_exit(seeded) -> None:
    run = seeded(
        _recharge_only(),
        policy="consumers",
        kept_terms=["recharge", *budget_terms_for("release_flux")],
    )

    spec = runs._get_figure("downslope_distance_map").spec
    assert "no drain, stream, lake or surface excess" in runs._no_surface_exit_reason(run, spec)


def test_a_consumers_run_that_kept_only_some_exits_stays_actionable(seeded) -> None:
    run = seeded(_recharge_only(), policy="consumers", kept_terms=["recharge", "drain"])

    spec = runs._get_figure("downslope_distance_map").spec
    assert runs._no_surface_exit_reason(run, spec) is None


def test_an_all_store_with_no_term_at_all_is_not_judged(seeded) -> None:

    def _declare_no_term(sz: SimulationZarr) -> None:
        sz.root.require_group("budget").attrs.update({"policy": "all", "kept_terms": []})

    run = seeded({}, edit=_declare_no_term)

    spec = runs._get_figure("downslope_distance_map").spec
    assert runs._no_surface_exit_reason(run, spec) is None


def test_a_figure_with_only_optional_fields_logs_the_not_kept_skip(
    seeded, tmp_path, caplog
) -> None:
    run = seeded(_recharge_only(), policy="consumers", kept_terms=["recharge"])
    cfg = DisplayConfig(figures=["boundary_package_map"], save=False)

    with caplog.at_level(logging.DEBUG, logger="hydromodpy.display.runs"):
        report = runs.render_figures_for_run(run, cfg, output_dir=tmp_path / "figures")

    (skip,) = report.skipped
    assert skip.actionable
    (record,) = [r for r in caplog.records if "boundary_package_map" in r.getMessage()]
    assert record.levelno == logging.WARNING
    assert ".." not in record.getMessage()
    assert "keep_per_cell_budget = true" in record.getMessage()

"""A figure built on the surface outflow is skipped on a model without exit.

A model with no drain, stream, lake or surface excess releases no groundwater
at the surface, so ``release_flux`` does not exist. The field is rebuilt on
read, so nothing stops the run: the figure is skipped with that reason, and
the skip is not actionable, since no option adds an exit to the model.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.display import runs
from hydromodpy.display.config import DisplayConfig
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.run import Run

N_STEPS = 2
N_CELLS = 4


def _seed(catalog: Catalog, budget: dict[str, np.ndarray]) -> str:
    sid = str(uuid.uuid4())
    reg = catalog.register_simulation(
        sid, project="p", solver="modflow6", n_cells=N_CELLS, n_layers=1, n_timesteps=N_STEPS
    )
    reg.zarr.close()
    sz = catalog.open_zarr(sid)
    try:
        sz.write_field_stack("head", np.full((N_STEPS, 1, N_CELLS), 120.0))
        for name, values in budget.items():
            sz.write_field_stack(name, values, subgroup="budget")
        if budget:
            # What a run that kept the whole budget declares.
            sz.root["budget"].attrs.update({"policy": "all", "kept_terms": sorted(budget)})
    finally:
        sz.close()
    return sid


def _recharge_only() -> dict[str, np.ndarray]:
    return {"recharge": np.full((N_STEPS, 1, N_CELLS), 1e-5)}


@pytest.fixture
def catalog(tmp_path: Path):
    with Catalog(tmp_path / "workspace") as cat:
        yield cat


def test_a_run_without_an_exit_does_not_serve_the_release_flux(catalog) -> None:
    sid = _seed(catalog, _recharge_only())

    assert not Run(sid, catalog).has_field("release_flux")


def test_the_figure_is_skipped_with_the_physical_reason(catalog, tmp_path, caplog) -> None:
    sid = _seed(catalog, _recharge_only())
    run = Run(sid, catalog)
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


def test_a_drain_only_figure_names_the_drain(catalog) -> None:
    sid = _seed(catalog, _recharge_only())
    run = Run(sid, catalog)

    reason = runs.unavailable_reason(runs._get_figure("accumulation_map"), run)

    assert reason is not None
    assert "the model has no drain," in reason
    assert "accumulation_flux" in reason


def test_a_model_with_a_drain_keeps_the_figure_reason(catalog) -> None:
    budget = _recharge_only()
    budget["drain"] = np.full((N_STEPS, 1, N_CELLS), -1e-4)
    sid = _seed(catalog, budget)
    run = Run(sid, catalog)

    assert run.has_field("release_flux")
    assert (
        runs._no_surface_exit_reason(run, runs._get_figure("downslope_distance_map").spec) is None
    )


def test_a_run_without_budget_is_not_judged(catalog) -> None:
    sid = _seed(catalog, {})
    run = Run(sid, catalog)

    spec = runs._get_figure("downslope_distance_map").spec
    assert runs._no_surface_exit_reason(run, spec) is None

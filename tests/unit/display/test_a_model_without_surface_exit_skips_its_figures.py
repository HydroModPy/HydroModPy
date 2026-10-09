"""A figure built on the surface outflow is skipped on a model without exit.

A model with no drain, stream, lake or surface excess releases no groundwater
at the surface, so ``release_flux`` does not exist. When a requested figure is
what turned the field on, the derive step goes on and the figure is skipped
with that reason. A field the user asked for still stops the run.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.core.exceptions import ExtractError
from hydromodpy.display import runs
from hydromodpy.display.config import DisplayConfig
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.run import Run
from hydromodpy.simulation.extraction.derivation.derived import FIGURE_REQUEST, compute_derived

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
    finally:
        sz.close()
    return sid


def _recharge_only() -> dict[str, np.ndarray]:
    return {"recharge": np.full((N_STEPS, 1, N_CELLS), 1e-5)}


@pytest.fixture
def catalog(tmp_path: Path):
    with Catalog(tmp_path / "workspace") as cat:
        yield cat


def test_a_field_a_figure_asked_for_does_not_stop_the_run(catalog, caplog) -> None:
    sid = _seed(catalog, _recharge_only())

    with caplog.at_level(logging.INFO):
        compute_derived(sid, catalog, {"release_flux": FIGURE_REQUEST})

    assert "Derived field 'release_flux' not computed" in caplog.text
    assert "expected a drain, stream, lake or surface excess" in caplog.text


def test_a_field_the_user_asked_for_still_stops_the_run(catalog) -> None:
    sid = _seed(catalog, _recharge_only())

    with pytest.raises(ExtractError, match="spatial_fields"):
        compute_derived(sid, catalog, {"release_flux": True})


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
    assert "Set [simulation.results.derived]" not in caplog.text


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

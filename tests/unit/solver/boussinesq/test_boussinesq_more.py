"""The Boussinesq driver builds its mesh, reports a failed start and a failed export.

Heads are in m, rates in m/s. The row mesh has 6 cells of 10 m by 10 m, 50 m thick.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.mesh.io.bundle import load_catchment_mesh_bundle
from hydromodpy.model.initial.state import SteadyStart
from hydromodpy.model.model import ModelTime
from hydromodpy.model.sinks_sources.recharge import FlowRechargeConfig
from hydromodpy.solver.boussinesq.boussinesq import Boussinesq
from hydromodpy.solver.boussinesq.drivers import steady as steady_driver
from hydromodpy.solver.boussinesq.options import BoussinesqOptions
from tests._helpers.mesh_cases import MESH_BUNDLES
from tests._helpers.model_factory import make_model

from ._row_runs import DAY_S, fixed_forcing, row_mesh

BUNDLE = "hantush_recharge_mound_tri_conforming"
TOP_M, BOTTOM_M = 10.0, 0.0


def bundle_with_properties():
    """A committed mesh bundle whose cells are 10 m thick, K = 1e-5 m/s and Sy = 0.1."""
    bundle = load_catchment_mesh_bundle(MESH_BUNDLES / BUNDLE)
    cells = tuple(
        replace(
            cell,
            z_top_centroid=TOP_M,
            z_bottom_centroid=BOTTOM_M,
            hydraulic_conductivity_m_s=1.0e-5,
            storage_coefficient=0.1,
        )
        for cell in bundle.cells
    )
    return replace(bundle, cells=cells)


def row_solver(tmp_path: Path, model, **runtime_options) -> Boussinesq:
    (tmp_path / "run").mkdir(exist_ok=True)
    return Boussinesq(
        mesh_bundle=None,
        mesh=row_mesh(),
        model=model,
        runtime=BoussinesqOptions(backend="local", tol_residual_inf=1.0e-12, **runtime_options),
        model_folder=tmp_path,
        model_name="run",
    )


def test_mesh_is_built_from_the_bundle(tmp_path: Path) -> None:
    bundle = bundle_with_properties()
    solver = Boussinesq(
        mesh_bundle=bundle,
        model=make_model(),
        runtime=BoussinesqOptions(),
        model_folder=tmp_path,
        model_name="run",
    )

    assert solver.processing(run_model=False) is True

    assert solver.runtime_summary["n_cells"] == bundle.n_cells
    assert solver.runtime_summary["bundle_dir"] == str(solver.mesh.bundle_dir)
    # The default start is the land surface.
    np.testing.assert_array_equal(solver.state.head_m, np.full(bundle.n_cells, TOP_M))


def test_refuses_a_run_without_mesh() -> None:
    with pytest.raises(ValueError, match="either mesh_bundle or a prebuilt mesh"):
        Boussinesq(
            mesh_bundle=None,
            mesh=None,
            model=make_model(),
            runtime=BoussinesqOptions(),
            model_folder=".",
            model_name="run",
        )


def test_failed_steady_start_stops_the_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(steady_driver, "resolve_runtime_forcing_by_period", fixed_forcing((1e-8,)))
    grid = SimpleNamespace(period_lengths_seconds=np.asarray([10.0 * DAY_S]), nstp_per_period=1)
    model = make_model(
        time=ModelTime(grid=grid, regime="transient", first_period_steady=False),
        initial=SteadyStart(),
        recharge=FlowRechargeConfig(values=[1.0e-8], units="m/s", first_clim=1.0e-9),
    )
    # One Newton iteration cannot close the steady balance of a row started at the top.
    solver = row_solver(tmp_path, model, max_iterations=1)

    assert solver.processing(run_model=True) is False

    assert solver.has_numerical_solution is False
    assert solver.solve_stage == "post_processed"
    summary = json.loads((tmp_path / "run" / "_boussinesq_summary.json").read_text())
    assert summary["has_numerical_solution"] is False


def test_failed_export_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(steady_driver, "resolve_runtime_forcing_by_period", fixed_forcing((1e-8,)))
    solver = row_solver(tmp_path, make_model())
    # A folder where the summary file belongs makes the export fail.
    (tmp_path / "run" / "_boussinesq_summary.json").mkdir()

    with pytest.raises(RuntimeError, match="post-processing failed"):
        solver.processing(run_model=True)

    assert solver.solve_stage == "post_processing_failed"

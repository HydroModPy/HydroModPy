"""The setup steps."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from hydromodpy.calibration.optim.parameters import ParameterSpace
from hydromodpy.core.runtime.bounds import Bounds
from hydromodpy.workflow.steps.dependencies import earliest_affected_step
from hydromodpy.workflow.steps.sequence import standard_steps
from hydromodpy.workflow.steps.setup import resolve_geographic_inputs

# --- test_stream_geometry_resolution ---
# Hand the network map of ``[data.hydrography]`` to the geographic step, for alpha only.


def _run_state(tmp_path: Path, *, config_path: Path | None = None) -> Any:
    return SimpleNamespace(
        config_path=config_path or tmp_path / "project.toml",
        setup=SimpleNamespace(workspace=None),
        bounds=Bounds(),
        inputs=None,
    )


def _cfg(*, sources=(), synthetic=False) -> Any:
    return SimpleNamespace(
        geographic=SimpleNamespace(uses_synthetic_geographic=lambda: synthetic),
        data=SimpleNamespace(hydrography=SimpleNamespace(sources=list(sources))),
    )


def _custom(path):
    return SimpleNamespace(source="file", path=str(path), force_refresh=False)


def test_no_hydrography_source_means_alpha_does_not_run(tmp_path):
    assert resolve_geographic_inputs(_cfg(sources=[]), _run_state(tmp_path)) is None


def test_a_source_holding_no_vector_resolves_to_nothing_without_raising(tmp_path):
    raster = tmp_path / "network.tif"
    raster.touch()
    cfg = _cfg(sources=[_custom(raster)])

    assert resolve_geographic_inputs(cfg, _run_state(tmp_path)) is None


def test_an_api_source_resolves_to_nothing(tmp_path):
    cfg = _cfg(sources=[SimpleNamespace(source="osm", path=None, force_refresh=False)])

    assert resolve_geographic_inputs(cfg, _run_state(tmp_path)) is None


# --- test_a_trial_moves_the_aquifer_geometry ---
# A trial that moves the thickness solves the thickness it moved.
#
# The calibration prefix builds the domain once and every trial forks from it,
# sharing the domain by reference. ``setup_process`` owns ``domain.depth_model``,
# so a trial that moves the thickness re-runs from there; until it rebuilt the
# substratum, it re-ran a step that never read the value, and every trial solved
# the geometry of the prefix under a different number.
#
# The project below is synthetic, so no terrain engine runs, and the check stops
# at the solver grid: no binary is needed to read ``botm``.

PROJECT_TOML = """
[workflow]
mode = "simulation"

[simulation]
name = "thickness_trial"

[[simulation.process]]
id = "flow"
kind = "flow"
solvers = ["modflow6"]

[workspace]

[geographic]
source_mode = "synthetic"
crs_project = "EPSG:2154"

[geographic.synthetic]
case_id = "thickness_trial"

[geographic.synthetic.grid]
length_x = "1000 m"
length_y = "1000 m"
nx = 20
ny = 20

[geographic.synthetic.topography]
kind = "linear"
base_elevation = 20.0
right_to_left_amplitude = 5.0

[domain.depth_model]
{depth_model}

[flow]
flow_regime = "steady"
param_list = ["K"]

[flow.param.K.field]
kind = "homogeneous"
value = "1e-5 m/s"

[display]
enabled = false
"""


def _prepare(tmp_path: Path, depth_model: str, path: str):
    from hydromodpy.project.trial_pipeline import fill_trial_pipeline

    fill_trial_pipeline()
    from hydromodpy.calibration.runners.trial import prepare_trials

    fill_trial_pipeline()
    config_path = tmp_path / "project.toml"
    config_path.write_text(
        PROJECT_TOML.format(root=tmp_path.as_posix(), depth_model=depth_model),
        encoding="utf-8",
    )
    space = ParameterSpace.from_toml_mapping(
        {"h": {"bounds": [-100.0, 300.0], "path": path, "units": "m"}}
    )
    return prepare_trials(config_path, override_paths={"h": path}, parameter_space=space)


def _run_setup_process(trial) -> None:
    from hydromodpy.workflow.runner import Pipeline
    from hydromodpy.workflow.state import PipelineState

    step = trial.downstream_steps[trial.earliest]
    assert step.name == "setup_process"
    state = PipelineState(
        run_id="thickness-trial",
        data={"cfg": trial.ctx.cfg, "ctx": trial.ctx, "skip_display": True},
    )
    Pipeline((step,)).run(state)


def _column_depth(domain, *, cell_mesh) -> np.ndarray:
    """Top minus botm of the solver grid the MODFLOW 6 build derives from the domain."""
    from hydromodpy.solver.modflow_grid.discretization_spatial import (
        build_spatial_discretization,
    )

    mesh = build_spatial_discretization(
        domain=domain, vertical_config=domain.config.layers, sgrid_config=None, cell_mesh=cell_mesh
    ).solver_mesh
    active = ~mesh.inactive_mask[0]
    return (mesh.top - mesh.botm[-1])[active]


def test_a_trial_solves_the_thickness_it_moved(tmp_path: Path) -> None:
    prepared = _prepare(
        tmp_path, 'kind = "constant_thickness"\nthickness = "30 m"', "domain.depth_model.thickness"
    )
    shared = prepared.ctx.setup.domain

    trial = prepared.fork({"h": 80.0})
    _run_setup_process(trial)

    cell_mesh = trial.ctx.setup.cell_mesh
    np.testing.assert_allclose(_column_depth(trial.ctx.setup.domain, cell_mesh=cell_mesh), 80.0)
    # The prefix keeps its own geometry for the next fork.
    assert prepared.ctx.setup.domain is shared
    np.testing.assert_allclose(_column_depth(shared, cell_mesh=cell_mesh), 30.0)


def test_a_trial_solves_the_substratum_elevation_it_moved(tmp_path: Path) -> None:
    prepared = _prepare(
        tmp_path,
        'kind = "flat_substratum"\nsubstratum_elevation = "0 m"',
        "domain.depth_model.substratum_elevation",
    )

    trial = prepared.fork({"h": -40.0})
    _run_setup_process(trial)

    bottom = trial.ctx.setup.domain.substratum.as_array()
    np.testing.assert_allclose(bottom[np.isfinite(bottom)], -40.0)

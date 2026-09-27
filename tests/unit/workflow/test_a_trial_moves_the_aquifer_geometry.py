"""A trial that moves the thickness solves the thickness it moved.

The calibration prefix builds the domain once and every trial forks from it,
sharing the domain by reference. ``setup_process`` owns ``domain.depth_model``,
so a trial that moves the thickness re-runs from there; until it rebuilt the
substratum, it re-ran a step that never read the value, and every trial solved
the geometry of the prefix under a different number.

The project below is synthetic, so no terrain engine runs, and the check stops
at the solver grid: no binary is needed to read ``botm``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.calibration.optim.parameters import ParameterSpace
from hydromodpy.workflow.internals.dependencies import earliest_affected_step
from hydromodpy.workflow.orchestrator import standard_steps

PROJECT_TOML = """
[workflow]
mode = "simulation"

[simulation]
name = "thickness_trial"

[[simulation.process]]
id = "flow"
type = "flow"
solvers = ["modflow6"]

[workspace]
project_root = "{root}"

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


def _index_of(name: str) -> int:
    return next(i for i, step in enumerate(standard_steps()) if step.name == name)


@pytest.mark.parametrize(
    "path", ["domain.depth_model.thickness", "domain.depth_model.substratum_elevation"]
)
def test_moving_the_geometry_re_runs_from_setup_process(path: str) -> None:
    assert earliest_affected_step([path], standard_steps()) == _index_of("setup_process")


@pytest.mark.parametrize(
    "path", ["domain.depth_model.thickness", "domain.depth_model.substratum_elevation"]
)
def test_the_mesh_guard_lets_the_geometry_through(path: str) -> None:
    space = ParameterSpace.from_toml_mapping({"h": {"bounds": [5.0, 300.0], "path": path}})

    assert space.parameters[0].effective_path == path


def _prepare(tmp_path: Path, depth_model: str, path: str):
    import hydromodpy
    from hydromodpy.calibration.runners.trial import prepare_trials

    hydromodpy.bootstrap()
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
    from hydromodpy.workflow.internals.state import PipelineState
    from hydromodpy.workflow.runner import Pipeline

    step = trial.downstream_steps[trial.earliest]
    assert step.name == "setup_process"
    state = PipelineState(
        run_id="thickness-trial",
        data={"cfg": trial.ctx.cfg, "ctx": trial.ctx, "skip_display": True},
    )
    Pipeline((step,)).run(state)


def _column_depth(domain, *, planar_mesh) -> np.ndarray:
    """Top minus botm of the solver grid the MODFLOW 6 build derives from the domain."""
    from hydromodpy.solver.modflow_grid.discretization_spatial import (
        build_spatial_discretization,
    )

    mesh = build_spatial_discretization(
        domain=domain, sgrid_config=None, runtime_planar_mesh=planar_mesh
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

    planar = trial.ctx.setup.mesh_planar
    np.testing.assert_allclose(_column_depth(trial.ctx.setup.domain, planar_mesh=planar), 80.0)
    # The prefix keeps its own geometry for the next fork.
    assert prepared.ctx.setup.domain is shared
    np.testing.assert_allclose(_column_depth(shared, planar_mesh=planar), 30.0)


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


def test_the_zones_of_the_shared_domain_carry_over(tmp_path: Path) -> None:
    prepared = _prepare(
        tmp_path, 'kind = "constant_thickness"\nthickness = "30 m"', "domain.depth_model.thickness"
    )
    zones = dict(prepared.ctx.setup.domain.zones)

    trial = prepared.fork({"h": 50.0})
    _run_setup_process(trial)

    assert trial.ctx.setup.domain.zones == zones


def test_a_run_whose_geometry_did_not_move_keeps_its_domain(tmp_path: Path) -> None:
    from hydromodpy.workflow.steps.setup import rebuild_substratum_if_depth_model_moved

    prepared = _prepare(
        tmp_path, 'kind = "constant_thickness"\nthickness = "30 m"', "domain.depth_model.thickness"
    )
    trial = prepared.fork({"h": 30.0})
    before = trial.ctx.setup.domain

    assert rebuild_substratum_if_depth_model_moved(trial.ctx) is False
    assert trial.ctx.setup.domain is before

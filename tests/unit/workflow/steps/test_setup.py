"""Setup steps: the geographic inputs a hydrography source gives, and the aquifer geometry of a trial.

A trial that moves the thickness or the substratum elevation (m) must solve the
geometry it moved. The calibration prefix builds the domain once and every trial
forks from it, sharing the domain by reference. The project is synthetic, so no
terrain engine runs, and the check stops at the solver grid: no binary is needed.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from hydromodpy.calibration.optim.parameters import ParameterSpace
from hydromodpy.core.runtime.bounds import Bounds
from hydromodpy.workflow.steps.setup import resolve_geographic_inputs


def run_state(tmp_path: Path) -> Any:
    return SimpleNamespace(
        config_path=tmp_path / "project.toml",
        setup=SimpleNamespace(workspace=None),
        bounds=Bounds(),
        inputs=None,
    )


# (source, file name written under tmp_path or None), one pair per hydrography source.
NO_VECTOR_SOURCES = [
    pytest.param([], id="no hydrography source"),
    pytest.param([("file", "network.tif")], id="a raster, no vector"),
    pytest.param([("osm", None)], id="an api source"),
]


@pytest.mark.parametrize("specs", NO_VECTOR_SOURCES)
def test_no_vector_resolves_to_nothing(tmp_path, specs) -> None:
    sources = []
    for source, name in specs:
        path = None if name is None else tmp_path / name
        if path is not None:
            path.touch()
        sources.append(SimpleNamespace(source=source, path=path, force_refresh=False))
    cfg = SimpleNamespace(
        geographic=SimpleNamespace(uses_synthetic_geographic=lambda: False),
        data=SimpleNamespace(hydrography=SimpleNamespace(sources=sources)),
    )

    assert resolve_geographic_inputs(cfg, run_state(tmp_path)) is None


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


def prepare(tmp_path: Path, depth_model: str, path: str):
    from hydromodpy.calibration.runners.trial import prepare_trials
    from hydromodpy.project.trial_pipeline import fill_trial_pipeline

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


def run_setup_process(trial) -> None:
    from hydromodpy.workflow.runner import Pipeline
    from hydromodpy.workflow.state import PipelineState

    step = trial.downstream_steps[trial.earliest]
    assert step.name == "setup_process"
    state = PipelineState(
        run_id="thickness-trial",
        data={"cfg": trial.ctx.cfg, "ctx": trial.ctx, "skip_display": True},
    )
    Pipeline((step,)).run(state)


def column_depth(domain, *, cell_mesh) -> np.ndarray:
    # Top minus botm of the solver grid the MODFLOW 6 build derives from the domain.
    from hydromodpy.solver.modflow_grid.discretization_spatial import (
        build_spatial_discretization,
    )

    mesh = build_spatial_discretization(
        domain=domain, vertical_config=domain.config.layers, sgrid_config=None, cell_mesh=cell_mesh
    ).solver_mesh
    active = ~mesh.inactive_mask[0]
    return (mesh.top - mesh.botm[-1])[active]


def test_trial_solves_moved_thickness(tmp_path: Path) -> None:
    prepared = prepare(
        tmp_path, 'kind = "constant_thickness"\nthickness = "30 m"', "domain.depth_model.thickness"
    )
    shared = prepared.ctx.setup.domain

    trial = prepared.fork({"h": 80.0})
    run_setup_process(trial)

    cell_mesh = trial.ctx.setup.cell_mesh
    np.testing.assert_allclose(column_depth(trial.ctx.setup.domain, cell_mesh=cell_mesh), 80.0)
    # The prefix keeps its own geometry for the next fork.
    assert prepared.ctx.setup.domain is shared
    np.testing.assert_allclose(column_depth(shared, cell_mesh=cell_mesh), 30.0)


def test_trial_solves_moved_substratum(tmp_path: Path) -> None:
    prepared = prepare(
        tmp_path,
        'kind = "flat_substratum"\nsubstratum_elevation = "0 m"',
        "domain.depth_model.substratum_elevation",
    )

    trial = prepared.fork({"h": -40.0})
    run_setup_process(trial)

    bottom = trial.ctx.setup.domain.substratum.as_array()
    np.testing.assert_allclose(bottom[np.isfinite(bottom)], -40.0)

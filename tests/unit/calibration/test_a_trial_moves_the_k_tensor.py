"""A calibration trial that moves K22 or an angle reaches the NPF arrays and XT3D.

A trial writes its sample into a copy of the configuration
(``TrialContext.fork``), and the flow of the trial is built again from it. So
K22 and the angles travel the path K travels: the catalog offers them, the
sample lands in ``flow.param``, the shared mapping puts it on every cell, and
the XT3D rule reads the arrays the build sets on the model. A trial that turns
the tensor off the grid axes gets XT3D, a trial that keeps it on them does not.

An angle is signed, so the catalog searches it as written. It used to inherit
the log search every field parameter declares for K, and a range such as
[-30, 30] was refused at load.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.calibration.runners.state import space_from_config
from hydromodpy.calibration.runners.trial import TrialContext
from hydromodpy.calibration.targets import calibration_targets, targets_by_name
from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.state.execution import ExecutionRegistry
from hydromodpy.simulation.execution.runner import ensure_flow
from hydromodpy.solver.modflow6.builders.solver_options import resolve_xt3d_decision
from hydromodpy.solver.modflow6.support.property_mapping import (
    K_TENSOR_NPF_NAMES,
    resolve_flow_property_arrays,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

PROJECT_TOML = """
[workflow]
mode = "calibration"

[workspace]

[geographic]
source_mode = "synthetic"
crs_project = "EPSG:2154"

[solver]
backend = { kind = "modflow6" }

[flow]
param_list = ["K", "K22", "angle1", "angle2"]

[flow.param.K.field]
kind = "homogeneous"
value = "1e-5 m/s"

[flow.param.K22.field]
kind = "homogeneous"
value = "1e-5 m/s"

[flow.param.angle1.field]
kind = "homogeneous"
value = 30.0

[flow.param.angle2.field]
kind = "homogeneous"
value = 0.0

[calibration]
variable = "head"
objective = "rmse"

[calibration.parameters.K22]
bounds = [1e-7, 1e-4]

[calibration.parameters.angle1]
bounds = [-90.0, 90.0]

[calibration.parameters.angle2]
bounds = [-30.0, 30.0]
"""


@pytest.fixture(scope="module")
def cfg(tmp_path_factory) -> HydroModPyConfig:
    path = tmp_path_factory.mktemp("k_tensor_trial") / "project.toml"
    path.write_text(PROJECT_TOML, encoding="utf-8")
    return HydroModPyConfig.from_toml(path)


def _mesh() -> SolverMesh:
    return solver_mesh_from_structured_arrays(
        nrow=2,
        ncol=2,
        top=np.full((2, 2), 30.0),
        botm=np.stack([np.full((2, 2), 20.0), np.zeros((2, 2))]),
    )


def _trial(cfg: HydroModPyConfig, tmp_path: Path, values: dict[str, float]) -> TrialContext:
    setup = SimpleNamespace(flow=None, transport=None, flow_runtime_overrides=None)
    ctx = SimpleNamespace(
        setup=setup, data_plan=None, loaded_data=SimpleNamespace(), execution=ExecutionRegistry()
    )
    base = TrialContext(
        base_cfg=cfg,
        ctx=ctx,
        earliest=0,
        downstream_steps=(),
        override_paths={},
        workspace=tmp_path,
        cfg_path=tmp_path / "project.toml",
        parameter_space=space_from_config(cfg.calibration),
    )
    return base.fork(values)


def _built_model(trial: TrialContext, mesh: SolverMesh) -> SimpleNamespace:
    """The model attributes ``run_pre_processing`` sets before its XT3D decision."""
    ensure_flow(trial.ctx)
    mapped = resolve_flow_property_arrays(
        flow=trial.ctx.setup.flow,
        domain=SimpleNamespace(zones={}),
        solver_mesh=mesh,
        required_properties=frozenset({"K"}),
    )
    runtime = SimpleNamespace(mf6_enable_xt3d=None)
    model = SimpleNamespace(modflow_config=SimpleNamespace(runtime=runtime))
    model.hk = mesh.flatten_from_grid(mapped["hk"])
    for name in K_TENSOR_NPF_NAMES:
        values = mapped.get(name)
        setattr(model, name, None if values is None else mesh.flatten_from_grid(values))
    return model


@pytest.mark.parametrize("name", ["angle1", "angle2"])
def test_the_catalogue_searches_an_angle_as_written(cfg, name: str) -> None:
    target = targets_by_name(calibration_targets(cfg))[name]
    assert target.calibrable is not None
    assert (target.calibrable.search_space, target.calibrable.sampling) == ("identity", "uniform")
    assert (
        cfg.calibration.parameters[name].search_space,
        cfg.calibration.parameters[name].sampling,
    ) == (
        "identity",
        "uniform",
    )


def test_k22_is_still_searched_in_log_space(cfg) -> None:
    assert cfg.calibration.parameters["K22"].search_space == "log"


def test_a_signed_angle_range_builds_a_parameter_space(cfg) -> None:
    space = space_from_config(cfg.calibration)
    assert {param.name for param in space} == {"K22", "angle1", "angle2"}


def test_the_trial_sample_reaches_every_cell_of_the_tensor(cfg, tmp_path: Path) -> None:
    trial = _trial(cfg, tmp_path, {"K22": 2e-6, "angle1": 45.0, "angle2": 12.0})
    model = _built_model(trial, _mesh())
    assert np.all(model.k22 == pytest.approx(2e-6))
    assert np.all(model.angle1 == 45.0)
    assert np.all(model.angle2 == 12.0)
    assert cfg.flow.param["K22"].field.value == pytest.approx(1e-5)


def test_the_base_tensor_keeps_xt3d_off(cfg, tmp_path: Path) -> None:
    model = _built_model(_trial(cfg, tmp_path, {}), _mesh())
    assert resolve_xt3d_decision(model, _mesh()).enabled is False


def test_a_trial_that_turns_k22_off_axis_gets_xt3d(cfg, tmp_path: Path) -> None:
    model = _built_model(_trial(cfg, tmp_path, {"K22": 1e-6}), _mesh())
    with pytest.warns(RuntimeWarning, match="K22 differs from K"):
        decision = resolve_xt3d_decision(model, _mesh())
    assert (decision.enabled, decision.source) == (True, "auto_on")


def test_a_trial_that_tilts_the_tensor_gets_xt3d(cfg, tmp_path: Path) -> None:
    model = _built_model(_trial(cfg, tmp_path, {"angle2": -8.0}), _mesh())
    with pytest.warns(RuntimeWarning, match="tilted"):
        assert resolve_xt3d_decision(model, _mesh()).enabled


def test_a_trial_that_brings_k22_back_on_axis_keeps_xt3d_off(cfg, tmp_path: Path) -> None:
    model = _built_model(_trial(cfg, tmp_path, {"K22": 1e-6, "angle1": 90.0}), _mesh())
    assert resolve_xt3d_decision(model, _mesh()).enabled is False

"""Checks made on the prepared model before the first solve of a calibration.

Bounds are probed by rebuilding the flow, a network criterion needs drains and
release packages whose conductance follows K (m/s), and the scored catchment
must be the delineated one (gap as a fraction of the catchment area).
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.config_network import CalibOutputNetwork
from hydromodpy.calibration.metrics import solver_extract
from hydromodpy.calibration.optim.parameters import ParameterSpace
from hydromodpy.calibration.runners import prepared_model, trial
from hydromodpy.calibration.runners.prepared_model import (
    _assert_active_release_packages_follow_k,
    _assert_bounds_valid,
    _assert_network_conductance_proportional,
)
from hydromodpy.calibration.runners.prepared_model import (
    _assert_the_scored_catchment_is_the_delineated_one as veto,
)
from hydromodpy.calibration.runners.trial import TrialContext, built_model, prepare_trials
from hydromodpy.core.exceptions import ObjectiveError
from hydromodpy.model.flow_config import FlowConfig
from hydromodpy.solver.modflow6.modflow6 import Modflow6

FLOOR = 1e-4  # lowest accepted specific yield


class ProbeFlow:
    value: float | None = None


class ProbeConfig:
    """Config double exposing the `flow` and `model_copy` contract used by the probe."""

    def __init__(self) -> None:
        self.flow = ProbeFlow()

    def model_copy(self, *, deep: bool = False) -> ProbeConfig:
        return ProbeConfig()


def param(name, lower, upper, path="flow.param.Sy.field.value", mode="replace"):
    return SimpleNamespace(name=name, lower=lower, upper=upper, effective_path=path, mode=mode)


def probe_ctx() -> SimpleNamespace:
    return SimpleNamespace(base_cfg=ProbeConfig())


@pytest.fixture()
def floor_flow(monkeypatch):
    """Build a fake flow that rejects an injected value below the floor."""

    def fake_apply(cfg, param, value):
        cfg.flow.value = value

    def fake_flow(*, config):
        v = getattr(config, "value", None)
        if v is not None and v < FLOOR:
            raise ValueError(f"specific yield value {v} outside [0.0001, 0.5]")
        return object()

    monkeypatch.setattr(
        "hydromodpy.calibration.optim.parameters.apply_parameter_to_config", fake_apply
    )
    monkeypatch.setattr("hydromodpy.model.flow.Flow", fake_flow)


@pytest.mark.fast
def test_low_bound_is_refused(floor_flow):
    with pytest.raises(ValueError, match=r"'Sy'.*lower bound.*outside the valid range"):
        _assert_bounds_valid(probe_ctx(), [param("Sy", 1e-7, 1e-1)])


ACCEPTED_BOUNDS = [
    pytest.param(
        [param("Sy", 1e-4, 1e-1), param("K", 1e-3, 1.0, path="flow.param.K.field.value")],
        id="bounds within the field range",
    ),
    pytest.param([param("free", 1e-9, 1.0, path=None)], id="params without path are skipped"),
    # A non-flow target is not covered by the flow rebuild probe.
    pytest.param(
        [param("alpha", 1e-9, 1.0, path="transport.param.alpha")], id="non flow params skipped"
    ),
]


@pytest.mark.fast
@pytest.mark.parametrize("space", ACCEPTED_BOUNDS)
def test_bounds_accepted_or_skipped(floor_flow, space):
    _assert_bounds_valid(probe_ctx(), space)


@pytest.mark.fast
def test_missing_config_is_noop():
    _assert_bounds_valid(SimpleNamespace(base_cfg=None), [])


def network_cfg() -> CalibrationConfig:
    return CalibrationConfig.model_validate(
        {
            "method": "grid",
            "outputs": {"net": {"support": "network", "map": {"complete": "streams.gpkg"}}},
            "objective_blocks": [
                {"name": "abherve", "metric": "distance_gap", "uses_outputs": ["net"]}
            ],
        }
    )


def single_metric_cfg(objective: str = "distance_gap") -> CalibrationConfig:
    """A phase config as the staged runner narrows it: only `variable` and `objective` remain."""
    return CalibrationConfig.model_validate(
        {"method": "grid", "variable": "net", "objective": objective}
    )


def head_cfg() -> CalibrationConfig:
    return CalibrationConfig.model_validate({"method": "grid", "variable": "head"})


def moving(*, moves_k: bool) -> list[SimpleNamespace]:
    path = "flow.param.K.field.value" if moves_k else "flow.param.Sy.field.value"
    return [param("K" if moves_k else "Sy", 1e-7, 1e-3, path=path)]


# Drain conductance of a network criterion: C = K * cell_area / drain_bed_thickness_m follows K
# only when the configured conductance is not strictly positive.


def drain_flow(value: float | None, *, active: bool = True):
    payload: dict[str, object] = {}
    if value is not None:
        payload["bc"] = {"drainage": {"kind": "drain", "value": value, "enabled": active}}
    elif active:
        payload["bc"] = {"drainage": {}}
    return FlowConfig.model_validate(payload)


def check_drain(flow, cfg, *, moves_k: bool = True) -> None:
    _assert_network_conductance_proportional(
        cfg, SimpleNamespace(base_cfg=SimpleNamespace(flow=flow)), moving(moves_k=moves_k)
    )


@pytest.mark.fast
def test_fixed_conductance_warns(caplog):
    with caplog.at_level(logging.WARNING):
        check_drain(drain_flow(1e-3), network_cfg(), moves_k=False)

    assert any("does not move a hydraulic conductivity" in rec.message for rec in caplog.records)


PASSING_DRAINS = [
    pytest.param(0.0, True, network_cfg(), id="the proportional fallback"),
    # Nothing declares a conductance, so nothing overrides the fallback.
    pytest.param(None, True, network_cfg(), id="an active boundary without a section"),
    pytest.param(1e-3, False, network_cfg(), id="an inactive drainage"),
    pytest.param(1e-3, True, head_cfg(), id="a calibration without a network output"),
]


@pytest.mark.fast
@pytest.mark.parametrize(("value", "active", "cfg"), PASSING_DRAINS)
def test_drain_conductances_pass(value, active, cfg):
    check_drain(drain_flow(value, active=active), cfg)


# SFR and LAK build their own conductance, never derived from K. DRN and CHD are fine.


def release_flow(active_bc: list[str]):
    tables = {
        "sfr": {"sinks_sources": {"sfr": {"main": {}}}},
        "lake": {"sinks_sources": {"lakes": {"l1": {"bedleak": 1.0, "initial_stage": 1.0}}}},
        "drainage": {"bc": {"drainage": {}}},
        "west_side": {"bc": {"west_side": {"kind": "dirichlet"}}},
    }
    payload: dict[str, dict] = {}
    for name in active_bc:
        for section, content in tables[name].items():
            payload.setdefault(section, {}).update(content)
    return FlowConfig.model_validate(payload)


def check_release(active_bc: list[str], *, moves_k: bool = True, cfg=None) -> None:
    _assert_active_release_packages_follow_k(
        network_cfg() if cfg is None else cfg,
        SimpleNamespace(base_cfg=SimpleNamespace(flow=release_flow(active_bc))),
        moving(moves_k=moves_k),
    )


RELEASE_REFUSALS = [
    pytest.param(["sfr"], single_metric_cfg(), "'net'", id="sfr with a single metric network"),
    pytest.param(["lake"], network_cfg(), "LAK", id="active lake when k moves"),
]


@pytest.mark.fast
@pytest.mark.parametrize(("active_bc", "cfg", "match"), RELEASE_REFUSALS)
def test_release_packages_refused(active_bc, cfg, match):
    with pytest.raises(ObjectiveError, match=match):
        check_release(active_bc, cfg=cfg)


PASSING_RELEASES = [
    pytest.param(["sfr"], {"cfg": single_metric_cfg("nse")}, id="a non network metric"),
    pytest.param(["sfr"], {"moves_k": False}, id="sfr when k does not move"),
    # DRN's conductance follows K, and CHD fixes a head.
    pytest.param(["drainage"], {}, id="drainage alone"),
    pytest.param(["west_side"], {}, id="a side chd alone"),
]


@pytest.mark.fast
@pytest.mark.parametrize(("active_bc", "options"), PASSING_RELEASES)
def test_release_packages_pass(active_bc, options):
    check_release(active_bc, **options)


# Veto on a scored catchment that is not the delineated one. The gap depends on the
# geometry alone, so one build answers for every trial.

NETWORK_MAP = {"support": "network", "map": {"complete": "map.gpkg"}}


def veto_cfg(**output) -> CalibrationConfig:
    return CalibrationConfig.model_validate(
        {
            "parameters": {"K": {"bounds": [1e-7, 1e-3], "path": "flow.param.K.field.value"}},
            "outputs": {"net": {**NETWORK_MAP, **output}},
            "objective_blocks": [
                {"name": "net", "metric": "distance_gap", "uses_outputs": ["net"]}
            ],
        }
    )


def k_space() -> ParameterSpace:
    return ParameterSpace.from_toml_mapping(
        {"K": {"bounds": [1e-7, 1e-3], "path": "flow.param.K.field.value"}}
    )


@pytest.fixture
def built(monkeypatch):
    """Serve a built model and a geometry whose gap the test sets."""
    seen = SimpleNamespace(builds=0, gap=0.0)

    class Built:
        def __enter__(self):
            seen.builds += 1
            return SimpleNamespace()

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(trial, "built_model", lambda *a, **k: Built())
    monkeypatch.setattr(
        solver_extract, "resolve_flow_adapter", lambda ctx: (object(), SimpleNamespace())
    )
    monkeypatch.setattr(solver_extract, "scored_catchment_mismatch", lambda *a: seen.gap)
    return seen


def bare_trial_ctx() -> TrialContext:
    return TrialContext(
        base_cfg=None,
        ctx=None,
        earliest=0,
        downstream_steps=(),
        override_paths={},
        workspace=Path("."),
        cfg_path=Path("x.toml"),
    )


def test_gap_above_bound_refused(built):
    built.gap = 0.11

    with pytest.raises(ObjectiveError, match=r"catchment_mismatch = 11\.0%.*5\.0% bound"):
        veto(veto_cfg(), bare_trial_ctx(), k_space())

    assert built.builds == 1


def test_synthetic_domain_has_no_gap(built):
    built.gap = float("nan")

    veto(veto_cfg(), bare_trial_ctx(), k_space())


def test_larger_bound_accepts_gap(built):
    built.gap = 0.11

    veto(veto_cfg(verdict={"max_catchment_mismatch": 0.2}), bare_trial_ctx(), k_space())


def test_veto_runs_with_checks(built, monkeypatch):
    built.gap = 0.5
    monkeypatch.setattr(prepared_model, "_assert_bounds_valid", lambda *a: None)

    with pytest.raises(ObjectiveError, match="catchment_mismatch"):
        prepared_model.check_the_prepared_model(veto_cfg(), bare_trial_ctx(), k_space())


def test_true_is_not_a_catchment_bound():
    with pytest.raises(ValidationError, match="write a share"):
        CalibOutputNetwork(map={"complete": "map.gpkg"}, verdict={"max_catchment_mismatch": True})


PROJECT_TOML = """
[workflow]
mode = "simulation"

[simulation]
name = "built"

[[simulation.process]]
id = "flow"
kind = "flow"
solvers = ["modflow6"]

[workspace]

[geographic]
source_mode = "synthetic"
crs_project = "EPSG:2154"

[geographic.synthetic]
case_id = "built"

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
kind = "constant_thickness"
thickness = "30 m"

[flow]
flow_regime = "steady"
param_list = ["K"]

[flow.param.K.field]
kind = "homogeneous"
value = "1e-5 m/s"

[display]
enabled = false
"""


@pytest.mark.parametrize(
    "override_paths",
    [{"K": "flow.param.K.field.value"}, ["flow.param.K.field.value"]],
    ids=["by_name", "by_path"],
)
def test_model_built_not_solved(tmp_path, monkeypatch, override_paths):
    def no_solve(self, *args, **kwargs):
        raise AssertionError("the model was to be built, not solved")

    monkeypatch.setattr(Modflow6, "processing", no_solve)
    path = tmp_path / "project.toml"
    path.write_text(PROJECT_TOML, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    trial_ctx = prepare_trials(path, override_paths=override_paths, parameter_space=k_space())

    with built_model(trial_ctx, {"K": 1e-5}) as ctx:
        _, run_ctx = solver_extract.resolve_flow_adapter(ctx)
        assert int(run_ctx.solver_run.solver_model.solver_mesh.n_cells) == 400
        assert np.isfinite(
            np.asarray(run_ctx.solver_run.solver_model.solver_mesh.top, dtype=float)
        ).all()
        folder = Path(run_ctx.solver_run.solver_model.full_path)

    assert not folder.exists()

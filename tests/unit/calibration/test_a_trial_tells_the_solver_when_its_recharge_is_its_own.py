"""``run_trial_light`` marks the sandbox only when the phase owns its recharge.

A trial always gets a private ``model_name_override``; it gets
``PRIVATE_TRIAL_RECHARGE_KEY`` on top only when its phase samples a value the
recharge is computed from (:func:`_trial_owns_its_recharge`). MODFLOW 6 reads
the key to decide whether this trial writes its RCHA/EVTA binaries into its
own ``_recharge`` folder or into the folder every trial of the phase shares.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.runners.trial import TrialContext, run_trial_light
from hydromodpy.core.state.execution import ExecutionRegistry
from hydromodpy.solver.modflow6.builders.recharge import PRIVATE_TRIAL_RECHARGE_KEY


@pytest.fixture(scope="module", autouse=True)
def _ensure_bootstrap():
    """Wire the deferred TrialPipelineProvider before any run_trial_light call."""
    import hydromodpy

    hydromodpy.bootstrap()


@dataclass
class _FakeParam:
    value: float = 1.0


@dataclass
class _FakeSoil:
    ru: float = 150.0


@dataclass
class _FakeRecharge:
    soil: _FakeSoil = field(default_factory=_FakeSoil)
    values: float = 0.0


@dataclass
class _FakeSinksSources:
    recharge: _FakeRecharge = field(default_factory=_FakeRecharge)


@dataclass
class _FakeFlow:
    K: _FakeParam = field(default_factory=_FakeParam)
    sinks_sources: _FakeSinksSources = field(default_factory=_FakeSinksSources)


@dataclass
class _FakeCfg:
    flow: _FakeFlow = field(default_factory=_FakeFlow)

    def model_copy(self, *, deep: bool = False) -> _FakeCfg:
        import copy as _copy

        return _copy.deepcopy(self) if deep else _copy.copy(self)


@dataclass
class _FakeSetup:
    workspace: Any = None
    geographic: Any = None
    mesh_planar: Any = None
    domain: Any = None
    flow: Any = None
    transport: Any = None
    flow_runtime_overrides: Any = None
    run_id: str = "toy"
    time_grid: Any = None


@dataclass
class _FakeLoadedData:
    hydrometry: Any = None


@dataclass
class _FakeCtx:
    cfg: _FakeCfg
    config_path: Path
    raw_toml: dict[str, Any]
    data_plan: Any = None
    setup: _FakeSetup = field(default_factory=_FakeSetup)
    loaded_data: _FakeLoadedData = field(default_factory=_FakeLoadedData)
    execution: ExecutionRegistry = field(default_factory=ExecutionRegistry)
    store: Any = None
    sim_id: Any = None


def _trial_context(tmp_path: Path, *, parameter_space: ParameterSpace | None) -> TrialContext:
    cfg = _FakeCfg()
    ctx = _FakeCtx(cfg=cfg, config_path=tmp_path / "hydromodpy.toml", raw_toml={})
    # earliest=9 with no downstream steps: run_trial_light skips the pipeline
    # slice entirely and only exercises fork() + the metric extractor, which is
    # all this contract needs.
    return TrialContext(
        base_cfg=cfg,
        ctx=ctx,
        earliest=9,
        downstream_steps=(),
        override_paths={"K": "flow.K.value"},
        workspace=tmp_path,
        cfg_path=tmp_path / "hydromodpy.toml",
        raw_toml={},
        parameter_space=parameter_space,
    )


def _run_and_capture_overrides(
    trial_ctx: TrialContext, values: dict[str, float], *, trial_id: int | None
) -> dict[str, Any] | None:
    captured: list[dict[str, Any] | None] = []

    def _metric(ctx, *, objective, variable):
        overrides = ctx.setup.flow_runtime_overrides
        captured.append(dict(overrides) if overrides is not None else None)
        return 0.0, {}

    run_trial_light(trial_ctx, values, metric_fn=_metric, trial_id=trial_id)
    return captured[0]


class TestPrivateRechargeKey:
    def test_a_sampled_soil_recharge_marks_its_own_folder(self, tmp_path: Path) -> None:
        space = ParameterSpace(
            [
                CalibParameter(
                    name="ru", lower=0, upper=1000, path="flow.sinks_sources.recharge.soil.ru"
                )
            ]
        )
        trial_ctx = _trial_context(tmp_path, parameter_space=space)
        overrides = _run_and_capture_overrides(trial_ctx, {"ru": 120.0}, trial_id=1)
        assert overrides == {
            "model_name_override": "toy_trial000001",
            PRIVATE_TRIAL_RECHARGE_KEY: True,
        }

    def test_a_phase_that_samples_only_k_shares_the_recharge(self, tmp_path: Path) -> None:
        space = ParameterSpace(
            [CalibParameter(name="K", lower=1e-6, upper=1e-2, path="flow.K.value")]
        )
        trial_ctx = _trial_context(tmp_path, parameter_space=space)
        overrides = _run_and_capture_overrides(trial_ctx, {"K": 1.0}, trial_id=2)
        assert overrides == {"model_name_override": "toy_trial000002"}

    def test_a_trial_without_an_id_gets_no_overrides_at_all(self, tmp_path: Path) -> None:
        space = ParameterSpace(
            [
                CalibParameter(
                    name="ru", lower=0, upper=1000, path="flow.sinks_sources.recharge.soil.ru"
                )
            ]
        )
        trial_ctx = _trial_context(tmp_path, parameter_space=space)
        overrides = _run_and_capture_overrides(trial_ctx, {"ru": 100.0}, trial_id=None)
        assert overrides is None

"""``_trial_owns_its_recharge`` reads what THIS phase samples, not what it reruns.

A phase after a frozen recharge phase carries ``soil.ru`` in
``override_paths`` (it reruns the value) without carrying it in
``parameter_space`` (it does not search over it). Only the second one means
the phase owns its own recharge folder.
"""

from __future__ import annotations

from pathlib import Path

from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.runners.trial import TrialContext, _trial_owns_its_recharge


def _trial_context(
    *,
    parameter_space: ParameterSpace | None = None,
    override_paths: dict[str, str] | None = None,
) -> TrialContext:
    return TrialContext(
        base_cfg=None,
        ctx=None,
        earliest=0,
        downstream_steps=(),
        override_paths=override_paths or {},
        workspace=Path("."),
        cfg_path=Path("hydromodpy.toml"),
        parameter_space=parameter_space,
    )


class TestSampledSpaceDecides:
    def test_a_sampled_soil_ru_owns_the_recharge(self) -> None:
        space = ParameterSpace(
            [
                CalibParameter(
                    name="ru", lower=0, upper=1000, path="flow.sinks_sources.recharge.soil.ru"
                )
            ]
        )
        assert _trial_owns_its_recharge(_trial_context(parameter_space=space)) is True

    def test_a_sampled_recharge_rate_owns_the_recharge(self) -> None:
        space = ParameterSpace(
            [
                CalibParameter(
                    name="rch", lower=0.0, upper=1.0, path="flow.sinks_sources.recharge.values"
                )
            ]
        )
        assert _trial_owns_its_recharge(_trial_context(parameter_space=space)) is True

    def test_a_phase_that_samples_only_k_does_not_own_the_recharge(self) -> None:
        space = ParameterSpace(
            [CalibParameter(name="K", lower=1e-6, upper=1e-2, path="flow.K.value")]
        )
        assert _trial_owns_its_recharge(_trial_context(parameter_space=space)) is False

    def test_a_frozen_soil_ru_reran_but_not_sampled_does_not_own_the_recharge(self) -> None:
        # Phase K after phase RU: soil.ru is frozen and reran (override_paths),
        # but this phase's own parameter_space only searches over K.
        space = ParameterSpace(
            [CalibParameter(name="K", lower=1e-6, upper=1e-2, path="flow.K.value")]
        )
        ctx = _trial_context(
            parameter_space=space,
            override_paths={
                "K": "flow.K.value",
                "ru": "flow.sinks_sources.recharge.soil.ru",
            },
        )
        assert _trial_owns_its_recharge(ctx) is False


class TestNoParameterSpaceFallsBackToOverridePaths:
    def test_a_recharge_path_among_the_override_paths_owns_it(self) -> None:
        ctx = _trial_context(override_paths={"ru": "flow.sinks_sources.recharge.soil.ru"})
        assert _trial_owns_its_recharge(ctx) is True

    def test_a_non_recharge_override_path_does_not_own_it(self) -> None:
        ctx = _trial_context(override_paths={"K": "flow.K.value"})
        assert _trial_owns_its_recharge(ctx) is False

"""Optuna adapter - TPE / CMA-ES / Random / NSGA-II.

This is the **recommended** adapter for new calibrations. Optuna manages the
sampler state natively via its ``ask()`` / ``tell()`` API.
"""

from __future__ import annotations

import warnings
from typing import Any, Literal

from hydromodpy.calibration.optim.method_config import OptunaMethodConfig
from hydromodpy.calibration.optim.optimizer import (
    EngineTraits,
    EvaluationResult,
    ParamSuggestion,
    best_completed,
)
from hydromodpy.calibration.optim.parameters import ParameterSpace, refuse_normal_sampling

# Optuna marks ``constant_liar`` as experimental when a sampler is built with it, and
# the warning names this module because the call is made here.
_EXPERIMENTAL_ARGUMENT = {
    "message": r".*experimental.*The interface can change in the future",
    "category": Warning,
    "module": r"hydromodpy\.calibration\.optim\.adapters\.optuna_adapter",
}
warnings.filterwarnings("ignore", **_EXPERIMENTAL_ARGUMENT)


def _samplers(optuna_module):
    return {
        "tpe": optuna_module.samplers.TPESampler,
        "random": optuna_module.samplers.RandomSampler,
        "cmaes": optuna_module.samplers.CmaEsSampler,
        "nsga": optuna_module.samplers.NSGAIISampler,
    }


class OptunaAdapter:
    """Drive an Optuna study via ask/tell."""

    name = "optuna"
    options = OptunaMethodConfig
    traits = EngineTraits(libraries=("optuna",), draws_a_normal=False, takes_width=True)

    def __init__(
        self,
        space: ParameterSpace,
        *,
        sampler: str = "tpe",
        seed: int | None = None,
        direction: Literal["minimize"] = "minimize",
        width: int = 1,
    ):
        import optuna

        self._optuna = optuna
        samplers = _samplers(optuna)
        if sampler not in samplers:
            raise ValueError(f"Unknown Optuna sampler {sampler!r}. Choices: {sorted(samplers)}")
        for param in space.parameters:
            refuse_normal_sampling("optuna", param.name, param.sampling)
        self.space = space
        sampler_cls = samplers[sampler]
        sampler_kwargs = {"seed": seed} if seed is not None else {}
        if sampler == "tpe" and width > 1:
            # The trials of a batch are asked before any is told. Counting the ones in
            # flight as the worst so far keeps the next points from landing on them.
            # Measured on analytic costs: neutral at a width of 2, better from 4.
            sampler_kwargs["constant_liar"] = True
        sampler_obj = sampler_cls(**sampler_kwargs)
        # Silence optuna's INFO chatter unless user overrides externally.
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        self._study = optuna.create_study(sampler=sampler_obj, direction=direction)
        self._pending: dict[int, Any] = {}
        self._history: list[EvaluationResult] = []
        self._trial_id = 0

    def ask(self, n: int = 1) -> list[ParamSuggestion]:
        out: list[ParamSuggestion] = []
        for _ in range(n):
            trial = self._study.ask()
            values: dict[str, float] = {}
            for p in self.space.parameters:
                trial.set_user_attr(f"{p.name}.sampling", p.sampling)
                trial.set_user_attr(f"{p.name}.search_space", p.search_space)
                if p.sampling == "log_uniform" and p.search_space == "identity":
                    values[p.name] = trial.suggest_float(p.name, p.lower, p.upper, log=True)
                    continue
                y = trial.suggest_float(p.name, p.lower_transformed, p.upper_transformed)
                values[p.name] = p.to_physical(y)
            self._trial_id += 1
            self._pending[self._trial_id] = trial
            out.append(ParamSuggestion(trial_id=self._trial_id, values=values, source="ask"))
        return out

    def suggest_next(self) -> ParamSuggestion:
        return self.ask(1)[0]

    def tell(self, results: list[EvaluationResult]) -> None:
        for r in results:
            trial = self._pending.pop(r.trial_id, None)
            if trial is None:
                continue
            if r.status == "completed":
                self._study.tell(trial, r.cost)
            else:
                self._study.tell(trial, state=self._optuna.trial.TrialState.FAIL)
            self._history.append(r)

    def best(self) -> EvaluationResult | None:
        return best_completed(self._history)

    def converged(self) -> bool:
        # Optuna has no natural convergence - budget is driven by the engine.
        return False


__all__ = ["OptunaAdapter"]

"""Optuna adapter — TPE / CMA-ES / Random / NSGA-II.

This is the **recommended** adapter for new calibrations. Optuna manages the
sampler state natively via its ``ask()`` / ``tell()`` API.
"""

from __future__ import annotations

import optuna

from hydromodpy.calibration.optimizer import (
    EvaluationResult,
    ParamSuggestion,
    register_optimizer,
)
from hydromodpy.calibration.parameters import ParameterSpace


_SAMPLERS = {
    "tpe": optuna.samplers.TPESampler,
    "random": optuna.samplers.RandomSampler,
    "cmaes": optuna.samplers.CmaEsSampler,
    "nsga": optuna.samplers.NSGAIISampler,
}


@register_optimizer("optuna")
class OptunaAdapter:
    """Drive an Optuna study via ask/tell."""

    name = "optuna"

    def __init__(
        self,
        space: ParameterSpace,
        *,
        sampler: str = "tpe",
        seed: int | None = None,
        direction: str = "minimize",
    ):
        if sampler not in _SAMPLERS:
            raise ValueError(f"Unknown Optuna sampler {sampler!r}. Choices: {sorted(_SAMPLERS)}")
        self.space = space
        sampler_cls = _SAMPLERS[sampler]
        sampler_kwargs = {"seed": seed} if seed is not None else {}
        try:
            sampler_obj = sampler_cls(**sampler_kwargs)
        except TypeError:
            sampler_obj = sampler_cls()
        # Silence optuna's INFO chatter unless user overrides externally.
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        self._study = optuna.create_study(sampler=sampler_obj, direction=direction)
        self._pending: dict[int, optuna.trial.Trial] = {}
        self._history: list[EvaluationResult] = []
        self._trial_id = 0

    def ask(self, n: int = 1) -> list[ParamSuggestion]:
        out: list[ParamSuggestion] = []
        for _ in range(n):
            trial = self._study.ask()
            values: dict[str, float] = {}
            for p in self.space.parameters:
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
                self._study.tell(trial, r.objective_value)
            else:
                self._study.tell(trial, state=optuna.trial.TrialState.FAIL)
            self._history.append(r)

    def best(self) -> EvaluationResult | None:
        valid = [r for r in self._history if r.status == "completed"]
        if not valid:
            return None
        return min(valid, key=lambda r: r.objective_value)

    def converged(self) -> bool:
        # Optuna has no natural convergence — budget is driven by the engine.
        return False


__all__ = ["OptunaAdapter"]

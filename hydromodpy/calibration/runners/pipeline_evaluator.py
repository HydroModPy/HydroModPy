"""The evaluator that runs HydroModPy itself, and the default of every document.

It holds exactly what ``cli_runner`` held before it: a prepared trial context, a
RAM metric extractor, and the water-budget rejection threshold. The behaviour is
unchanged on purpose -- F9a moves the call behind a name, it does not move a
number. What it gains is a place: building the metric extractor needs
``trial_ctx.ctx``, so it belongs to the evaluator that owns a trial context and
not to a loop that is supposed to work without one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from hydromodpy.calibration.config import scoring_window_bounds
from hydromodpy.calibration.evaluation.port import TrialOutcome, TrialRequest
from hydromodpy.calibration.metrics.composite import build_metric_extractor

if TYPE_CHECKING:  # pragma: no cover - typing only
    from hydromodpy.calibration.config import CalibrationConfig
    from hydromodpy.calibration.runners.trial import TrialContext


class PipelineTrialEvaluator:
    """Score one parameter sample by running the HydroModPy pipeline on it.

    Built by :func:`hydromodpy.calibration.evaluation.registry.create`, which
    binds only the options this constructor names. ``metric_fn`` overrides the
    extractor built from the configuration; it is the escape hatch the three
    programmatic entry points already published.
    """

    evaluator_id: ClassVar[str] = "hydromodpy_pipeline"
    needs_prepared_model: ClassVar[bool] = True

    def __init__(
        self,
        *,
        cfg: CalibrationConfig,
        trial_ctx: TrialContext,
        metric_fn: Any | None = None,
    ) -> None:
        if trial_ctx is None:
            raise ValueError(
                f"{self.evaluator_id!r} declares needs_prepared_model, so it is built with the "
                "trial context prepare_trials returns. It was given none, which means the "
                "caller skipped the preparation this evaluator's every trial forks from."
            )
        self._cfg = cfg
        self._trial_ctx = trial_ctx
        self._metric_fn = metric_fn if metric_fn is not None else _extractor_for(cfg, trial_ctx)

    def evaluate(self, request: TrialRequest) -> TrialOutcome:
        """Run steps ``[earliest..8]`` on a fork of the context and score them."""
        from hydromodpy.calibration.runners.trial import run_trial_light

        result = run_trial_light(
            self._trial_ctx,
            request.values,
            objective=self._cfg.objective,
            variable=self._cfg.variable,
            metric_fn=self._metric_fn,
            trial_id=request.trial_id,
            reject_water_budget_above=self._cfg.reject_water_budget_above,
        )
        return TrialOutcome(
            cost=result.primary_metric,
            status=result.status,
            duration_s=result.duration_s,
            components=dict(result.metrics) if result.metrics else {},
            error=result.error,
        )


def _extractor_for(cfg: CalibrationConfig, trial_ctx: TrialContext) -> Any:
    """Return the RAM metric extractor the configuration describes.

    Every argument comes off ``cfg`` except the context, which is where the
    observations are loaded from. Kept as a function rather than inlined so the
    long argument list stays out of the constructor and reads as one thing.
    """
    return build_metric_extractor(
        cfg.variable,
        cfg.objective,
        trial_ctx.ctx,
        outputs=cfg.outputs or None,
        objective_blocks=cfg.objective_blocks or None,
        warmup_periods=int(cfg.warmup_periods),
        scoring_window=scoring_window_bounds(cfg.scoring_window),
        observed_station_id=cfg.observed_station_id,
        min_samples=int(cfg.aggregate.min_samples),
    )


__all__ = ["PipelineTrialEvaluator"]

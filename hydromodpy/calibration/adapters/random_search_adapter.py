"""Random-search adapter registered as ``random_search``.

Wraps :class:`~hydromodpy.calibration.adapters.optuna_adapter.OptunaAdapter`
with ``sampler="random"``. Kwargs map legacy names onto Optuna's:

- ``n_samples`` (legacy) → no direct Optuna knob, consumed at call site
  (the engine drives the loop via ``max_iter`` on the config).
- ``seed`` (legacy) → Optuna ``seed``.

The class itself does nothing fancy; it exists so the method name
``random_search`` resolves through the standard optimizer registry.
"""

from __future__ import annotations

from hydromodpy.calibration.adapters.optuna_adapter import OptunaAdapter
from hydromodpy.calibration.optimizer import register_optimizer
from hydromodpy.calibration.parameters import ParameterSpace


@register_optimizer("random_search")
class RandomSearchAdapter(OptunaAdapter):
    """Optuna :class:`RandomSampler` exposed under the legacy name."""

    name = "random_search"

    def __init__(
        self,
        space: ParameterSpace,
        *,
        seed: int | None = None,
        n_samples: int | None = None,
        **kwargs,
    ) -> None:
        del n_samples  # budget is controlled by CalibrationEngine.max_iter
        super().__init__(space, sampler="random", seed=seed, **kwargs)


__all__ = ["RandomSearchAdapter"]

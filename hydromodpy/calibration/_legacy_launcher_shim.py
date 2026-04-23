"""Import-time compatibility shim for the retired ``ModelCalibrationLauncher``.

The legacy ``hydromodpy.analysis.calibration.engine.{launcher,session}``
modules were removed when calibration moved onto the unified
``hmp run <calibration.toml>`` entry point (Phases 1-4 of the
calibration refactor). A handful of callers in
``validation_cases/calibration/`` - the twin-benchmark runner and its
standalone CLI helpers - still use the old launcher API.

Rather than keep those imports failing at module load (which also
breaks unrelated code living next to them), this module provides
drop-in names that import cleanly and raise
:class:`NotImplementedError` with an actionable message only when
actually called. Unblocking the imports is enough to:

- let the non-twin validation tests (groundwater_1d, recession_brutsaert,
  reservoir) keep passing even when someone imports
  ``validation_cases.calibration.shared.runtime`` indirectly,
- let editors and static analyzers resolve the top-level names,
- keep ``test_twin_*`` guarded by the existing
  ``collect_ignore_glob`` in ``tests/validation/calibration/conftest.py``
  until the full shape of the legacy summary + the per-session
  ``calibration_root/iteration_history.jsonl`` layout is replicated on
  top of :func:`hydromodpy.calibration.cli.run_calibration_cli`.
"""

from __future__ import annotations

from typing import Any

_UPGRADE_MESSAGE = (
    "ModelCalibrationLauncher has been retired. Calibration now runs through "
    "``hmp run <calibration.toml>`` (see docs/developers/calibration_guide.md). "
    "The twin-benchmark harness in validation_cases/calibration/shared/runtime.py "
    "still depends on the legacy summary/calibration_root layout; porting it to "
    "the new CLI is tracked as a follow-up to the calibration refactor."
)


class ModelCalibrationLauncher:
    """Retired; see :mod:`hydromodpy.calibration.cli`."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover
        raise NotImplementedError(_UPGRADE_MESSAGE)

    def calibrate(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        raise NotImplementedError(_UPGRADE_MESSAGE)

    def prepare(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        raise NotImplementedError(_UPGRADE_MESSAGE)


class ModelCalibrationObjectiveEvaluator:
    """Retired; use the ``run_trial_light`` primitive instead."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover
        raise NotImplementedError(_UPGRADE_MESSAGE)


def actualize_candidate(*args: Any, **kwargs: Any) -> Any:  # pragma: no cover
    raise NotImplementedError(_UPGRADE_MESSAGE)


def select_candidate_outputs(*args: Any, **kwargs: Any) -> Any:  # pragma: no cover
    raise NotImplementedError(_UPGRADE_MESSAGE)


__all__ = (
    "ModelCalibrationLauncher",
    "ModelCalibrationObjectiveEvaluator",
    "actualize_candidate",
    "select_candidate_outputs",
)

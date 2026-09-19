"""The trial-evaluator port and the registry that resolves one by name.

A calibration turns a parameter sample into a cost. What does the turning is
this port; which implementation does it is a name in the document, resolved
here. See :mod:`hydromodpy.calibration.evaluation.port` for why the port is an
evaluator and not a forward model.
"""

from hydromodpy.calibration.evaluation.port import (
    TrialEvaluator,
    TrialOutcome,
    TrialRequest,
    TrialStatus,
    evaluator_members,
)

__all__ = [
    "TrialEvaluator",
    "TrialOutcome",
    "TrialRequest",
    "TrialStatus",
    "evaluator_members",
]

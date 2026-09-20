"""The trial-evaluator port and the registry that resolves one by name.

A calibration turns a parameter sample into a cost. What does the turning is
this port; which implementation does it is a name in the document, resolved
here. See :mod:`hydromodpy.calibration.evaluation.port` for why the port is an
evaluator and not a forward model.

Three evaluators ship here. ``hydromodpy_pipeline`` runs the model and is the
default; it is imported only when a lookup asks for it, because it pulls the
workflow and solver stack behind it. ``analytic_bowl`` runs no model at all and
lives in :mod:`hydromodpy.calibration.evaluation.analytic_bowl`.
``scored_forward_model`` owns no physics either: it asks a forward model for the
observables the document declares and scores them with the document's criteria.

That second port is :mod:`hydromodpy.calibration.evaluation.forward` -- a
parameter sample in, named observables out -- resolved by name through
:mod:`hydromodpy.calibration.evaluation.forward_registry`. It is where a foreign
model joins without bringing a metric of its own.
"""

from hydromodpy.calibration.evaluation.forward import (
    ForwardModel,
    ForwardOutcome,
    ForwardRequest,
    forward_model_members,
)
from hydromodpy.calibration.evaluation.port import (
    TrialEvaluator,
    TrialOutcome,
    TrialRequest,
    TrialStatus,
    evaluator_members,
)

__all__ = [
    "ForwardModel",
    "ForwardOutcome",
    "ForwardRequest",
    "TrialEvaluator",
    "TrialOutcome",
    "TrialRequest",
    "TrialStatus",
    "evaluator_members",
    "forward_model_members",
]

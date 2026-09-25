"""The trial-evaluator port and the registry that resolves one by name.

A calibration turns a parameter sample into a cost. What does the turning is
this port; which implementation does it is a name in the document, resolved
here. See :mod:`hydromodpy.calibration.evaluation.port` for why the port is an
evaluator and not a forward model.

Three evaluators are registered here. ``analytic_bowl`` runs no model at all and
lives in :mod:`hydromodpy.calibration.evaluation.analytic_bowl`. The other two
read the calibration document, so they live above it and the registry names
them by a dotted path, imported only when a lookup asks for one.
``hydromodpy_pipeline`` runs the model and is the default; it lives in
:mod:`hydromodpy.calibration.runners.pipeline_evaluator`, beside the trial it
runs. ``scored_forward_model`` owns no physics: it asks a forward model for the
observables the document declares and scores them with the document's criteria;
it lives in :mod:`hydromodpy.calibration.metrics.scored_forward`.

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

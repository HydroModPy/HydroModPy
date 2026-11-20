"""The trial-evaluator port of a calibration, and the registry that resolves one by name.

A calibration turns a parameter sample into a cost. What does the turning is
the port; which implementation does it is a name in the document, resolved in
:mod:`hydromodpy.calibration.evaluation.registry`. The port itself,
:mod:`hydromodpy.calibration.evaluation.port`, is an evaluator: it owns how a
run is scored and nothing about what computes the values, so a criterion and a
weight are a change to the document and never a patch to an implementation.

The evaluators this build ships are named in the registry; a third party joins
the same way, through the ``hydromodpy.calibration.evaluator`` entry-point
group. Nothing is re-exported here: import the port for its vocabulary and the
registry for the names that resolve on an installation.
"""

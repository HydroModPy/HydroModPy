"""``evaluator_id -> TrialEvaluator class``, and the surface a third party registers on.

What was impossible before this module
--------------------------------------
The ask/tell loop has always accepted any callable, and eight construction sites
of this repository already pass one that is not the pipeline -- the two analytic
cases and the three validation experiments. The seam is real at that level.

The production path is where it was not. From a project TOML, through
``hmp calibrate``, the evaluator was built in one place and could not be anything
else: ``cli_runner`` called ``run_trial_light`` directly, and the trial context
that call demands can only come from ``prepare_trials``. The one published
injection point, ``metric_fn``, applies *after* the solve, over a context the
pipeline has already produced -- it changes how a run is scored, never what runs.
So "calibrate something else from a file" was not hard, it was impossible, which
is the same sentence the terrain registry opens with and the same reason.

No ``[project.entry-points]`` table for the in-tree evaluator, and that is D21
-----------------------------------------------------------------------------
The group is the out-of-tree surface only. The evaluator this tree ships is
declared once, in :data:`_BUILTIN_PATHS`, and imported on the first lookup that
asks for it -- so resolving a surrogate pulls in neither the workflow provider
nor the solver stack behind it. Declaring it in ``pyproject.toml`` as well would
give it a second name and a second source of truth.

Why a class, and why binding by parameter name
----------------------------------------------
:func:`get` returns the class and :func:`create` builds it, binding only the
constructor parameters the class names -- the rule the terrain and data-source
registries already use. It is what lets the runner hand out every option of
:data:`CONSTRUCTION_OPTIONS` without knowing which evaluator wants what: the
pipeline evaluator names the trial context, the analytic one names the space, and
a surrogate that needs neither is built with nothing.

:func:`needs_prepared_model` is read off the **class**, before anything is built,
because the answer decides whether the caller runs ``prepare_trials`` at all.
Asking an instance would mean building the instance first, and building the
in-tree one means already holding the context the question is about.
"""

from __future__ import annotations

from hydromodpy.calibration.evaluation.port import evaluator_members
from hydromodpy.core.exceptions import CalibrationError
from hydromodpy.core.plugin_registry import PluginRegistry

ENTRY_POINT_GROUP = "hydromodpy.calibration.evaluator"
"""The out-of-tree plugin group. One entry point per evaluator, named on its id."""

CONSTRUCTION_OPTIONS: tuple[str, ...] = (
    "cfg",
    "cfg_path",
    "metric_fn",
    "space",
    "trial_ctx",
    "workspace",
)
"""Every option the production path offers an evaluator's constructor.

:func:`create` binds only the parameters a class names, so this is the vocabulary
a third party writes its ``__init__`` in: a parameter named outside this tuple is
never filled, and one that is also required makes the evaluator unbuildable at
the first calibration that names it. The conformance suite holds an evaluator to
it, and a gate derived from the source holds ``runners.search`` to passing exactly
these -- one list, not two.

``trial_ctx`` is ``None`` for an evaluator that declares no prepared model, and
``cfg_path`` is ``None`` for a search launched programmatically rather than from
a document. The other four are always present.
"""

DEFAULT_EVALUATOR_ID = "hydromodpy_pipeline"
"""The evaluator a document that names none gets.

It is the one every calibrated number in this repository was produced with, so
the default is a compatibility statement and not a preference.
"""

_BUILTIN_PATHS: dict[str, str] = {
    "hydromodpy_pipeline": (
        "hydromodpy.calibration.runners.pipeline_evaluator:PipelineTrialEvaluator"
    ),
    "analytic_bowl": "hydromodpy.calibration.evaluation.analytic_bowl:AnalyticBowlEvaluator",
    "scored_forward_model": (
        "hydromodpy.calibration.metrics.scored_forward:ScoredForwardEvaluator"
    ),
}
"""Dotted paths to the in-tree evaluator classes, imported on first lookup.

Format ``"<module>:<class>"``, the one the terrain, solver and data-source
registries already use, so the plugin surfaces of this repository read alike.
"""

_ENGINE = PluginRegistry(
    kind="trial evaluator",
    id_attribute="evaluator_id",
    group=ENTRY_POINT_GROUP,
    builtin_paths=_BUILTIN_PATHS,
    members=evaluator_members,
    default_id=DEFAULT_EVALUATOR_ID,
    error=CalibrationError,
)
builtin_evaluator_ids = _ENGINE.builtin_ids
list_evaluator_ids = _ENGINE.list_ids
is_registered = _ENGINE.is_registered
register = _ENGINE.register
get = _ENGINE.get
resolve_id = _ENGINE.resolve_id
create = _ENGINE.create
load_plugins = _ENGINE.load_plugins
unregister = _ENGINE.unregister


def needs_prepared_model(evaluator_id: str | None = None) -> bool:
    """Whether the named evaluator requires HydroModPy's own trial context.

    Answered from the class, so a caller knows before running ``prepare_trials``
    -- which is the whole geographic, mesh and data prefix of the pipeline.

    No fallback, on purpose: :func:`register` refuses a class that does not carry
    the member, so every class :func:`get` can return has one. A default here
    would be unreachable code claiming a behavior nothing can produce.
    """
    return bool(get(evaluator_id).needs_prepared_model)


__all__ = [
    "DEFAULT_EVALUATOR_ID",
    "ENTRY_POINT_GROUP",
    "builtin_evaluator_ids",
    "create",
    "get",
    "is_registered",
    "list_evaluator_ids",
    "load_plugins",
    "needs_prepared_model",
    "register",
    "resolve_id",
    "unregister",
]

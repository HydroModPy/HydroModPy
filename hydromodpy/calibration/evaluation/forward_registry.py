"""``model_id -> ForwardModel class``, and the surface a third party registers on.

Same shape as the evaluator registry beside it, for the same reason: a document
names an implementation, this answers, and no file of ``hydromodpy/`` imports
one. What differs is what is resolved -- a model that produces observables,
scored afterwards by the criteria the document declares, rather than an
evaluator that produces a cost of its own making.

The in-tree model is declared in :data:`_BUILTIN_PATHS` and imported on the
first lookup that asks for it, never through ``[project.entry-points]``: the
group is the out-of-tree surface only, which is D21 and what the three sibling
registries already do.
"""

from __future__ import annotations

from hydromodpy.calibration.evaluation.forward import forward_model_members
from hydromodpy.core.exceptions import CalibrationError
from hydromodpy.core.plugin_registry import PluginRegistry

ENTRY_POINT_GROUP = "hydromodpy.calibration.forward_model"
"""The out-of-tree plugin group. One entry point per model, named on its id."""

CONSTRUCTION_OPTIONS: tuple[str, ...] = (
    "cfg",
    "cfg_path",
    "space",
    "workspace",
)
"""Every option the scoring evaluator offers a forward model's constructor.

:func:`create` binds only the parameters a class names, so this is the
vocabulary a third party writes its ``__init__`` in. It is a subset of the
evaluator registry's: ``trial_ctx`` and ``metric_fn`` belong to the pipeline
evaluator, and a model scored by the document's criteria is by construction one
that neither prepares a HydroModPy model nor brings a metric of its own.
"""

DEFAULT_FORWARD_MODEL_ID = "linear_reservoir"
"""The model a document that names none gets.

It runs no solver and its answer is closed-form, so what a document gets by
saying nothing is a rehearsal of its own criteria, weights and search -- not a
silent choice of physics. A study names its model.
"""

_BUILTIN_PATHS: dict[str, str] = {
    "linear_reservoir": (
        "hydromodpy.calibration.evaluation.linear_reservoir:LinearReservoirForwardModel"
    ),
}
"""Dotted paths to the in-tree model classes, imported on first lookup."""

_ENGINE = PluginRegistry(
    kind="forward model",
    id_attribute="model_id",
    group=ENTRY_POINT_GROUP,
    builtin_paths=_BUILTIN_PATHS,
    members=forward_model_members,
    default_id=DEFAULT_FORWARD_MODEL_ID,
    error=CalibrationError,
    construction_options=CONSTRUCTION_OPTIONS,
)
builtin_model_ids = _ENGINE.builtin_ids
list_model_ids = _ENGINE.list_ids
is_registered = _ENGINE.is_registered
register = _ENGINE.register
get = _ENGINE.get
resolve_id = _ENGINE.resolve_id
create = _ENGINE.create
load_plugins = _ENGINE.load_plugins
unregister = _ENGINE.unregister

__all__ = [
    "CONSTRUCTION_OPTIONS",
    "DEFAULT_FORWARD_MODEL_ID",
    "ENTRY_POINT_GROUP",
    "builtin_model_ids",
    "create",
    "get",
    "is_registered",
    "list_model_ids",
    "load_plugins",
    "register",
    "resolve_id",
    "unregister",
]

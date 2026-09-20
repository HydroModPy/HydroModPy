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

import importlib
import inspect
from importlib.metadata import entry_points

from hydromodpy.calibration.evaluation.forward import forward_model_members
from hydromodpy.core.exceptions import CalibrationError
from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)

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

_REGISTRY: dict[str, type] = {}
_PLUGINS_LOADED = False


def builtin_model_ids() -> tuple[str, ...]:
    """Return the ids this build ships, sorted, plugins excluded."""
    return tuple(sorted(_BUILTIN_PATHS))


def list_model_ids() -> tuple[str, ...]:
    """Return every id resolvable here, built-in and installed, sorted."""
    if not _PLUGINS_LOADED:
        load_plugins()
    return tuple(sorted(set(_REGISTRY) | set(_BUILTIN_PATHS)))


def is_registered(model_id: str) -> bool:
    """Whether :func:`get` would resolve *model_id* without raising."""
    return model_id in list_model_ids()


def register(model_cls: type, *, replace: bool = False) -> type:
    """Register a forward model class under the ``model_id`` it declares.

    The id is read off the class and never passed in, so a session record and
    the document that asked for it cannot name different models.

    Returns the class unchanged, so it can be used as a decorator.
    """
    model_id = getattr(model_cls, "model_id", None)
    if not isinstance(model_id, str) or not model_id.strip():
        raise TypeError(
            f"{_name_of(model_cls)!r} declares model_id={model_id!r} on the class, and a "
            "registry keyed on a name cannot hold a model that has none. It is a "
            "ClassVar[str] in the port; a value computed per instance is not readable here."
        )
    missing = _unusable_members(model_cls)
    if missing:
        raise TypeError(
            f"{_name_of(model_cls)!r} cannot serve {model_id!r}: it does not satisfy the "
            f"forward-model port, missing or unusable {', '.join(missing)}. Every trial "
            "calls them, so the gap would surface after the setup rather than here."
        )
    # Both mappings and two lookups compared against ``None``, for the reason
    # the evaluator registry states: an in-tree id is a declaration until the
    # first lookup imports it, and a class could otherwise claim the name of a
    # model this build ships and answer in its place.
    taken: object | None = _REGISTRY.get(model_id)
    if taken is None:
        taken = _BUILTIN_PATHS.get(model_id)
    if taken is not None and not replace:
        raise ValueError(
            f"A forward model is already registered for {model_id!r}: {_name_of(taken)}. "
            "Pass replace=True to substitute it, which is a deliberate in-process "
            "substitution the cache key cannot see."
        )
    _REGISTRY[model_id] = model_cls
    return model_cls


def get(model_id: str | None = None) -> type:
    """Return the forward model **class** registered under *model_id*.

    ``None`` resolves :data:`DEFAULT_FORWARD_MODEL_ID`. Resolution order is the
    cache, then the in-tree declaration, then one scan of the plugin group.

    Raises
    ------
    CalibrationError
        When no model answers to that name.
    """
    wanted = DEFAULT_FORWARD_MODEL_ID if model_id is None else model_id
    cls = _REGISTRY.get(wanted)
    if cls is not None:
        return cls
    cls = _load_builtin(wanted)
    if cls is not None:
        return cls
    if not _PLUGINS_LOADED:
        load_plugins()
        cls = _REGISTRY.get(wanted)
        if cls is not None:
            return cls
    known = ", ".join(sorted(set(_REGISTRY) | set(_BUILTIN_PATHS))) or "none"
    raise CalibrationError(
        f"No forward model is registered for {wanted!r}. This installation serves {known}. "
        f"A third-party model joins that list through the {ENTRY_POINT_GROUP!r} entry-point "
        "group, without a patch to HydroModPy."
    )


def resolve_id(model_id: str | None = None) -> str:
    """Return the id the class behind *model_id* declares for itself."""
    return str(get(model_id).model_id)


def create(model_id: str | None = None, **options: object) -> object:
    """Build the model registered under *model_id*, binding what it names.

    Only the constructor parameters the class declares are bound, the rule the
    evaluator, terrain and data-source registries already use.

    Raises
    ------
    CalibrationError
        From :func:`get`, when no model answers to that name; or when the
        constructor demands something this route cannot hand it -- an argument
        taken positionally only, which a keyword cannot fill, or one named
        outside :data:`CONSTRUCTION_OPTIONS`, which nothing here can supply.
    """
    model_cls = get(model_id)
    parameters = inspect.signature(model_cls).parameters
    positional_only = [
        name
        for name, parameter in parameters.items()
        if parameter.kind is inspect.Parameter.POSITIONAL_ONLY
        and parameter.default is inspect.Parameter.empty
    ]
    if positional_only:
        raise CalibrationError(
            f"Forward model {getattr(model_cls, 'model_id', model_cls)!r} takes "
            f"{', '.join(positional_only)} positionally only, and it is built from named "
            "options. Declare them as keyword parameters."
        )
    bindable = (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    # A required parameter nothing can fill, named here rather than left to the
    # constructor: the evaluator port holds its implementations to the same
    # rule, and a TypeError out of somebody else's __init__ says nothing about
    # which vocabulary this route speaks.
    unserved = [
        name
        for name, parameter in parameters.items()
        if parameter.kind in bindable
        and parameter.default is inspect.Parameter.empty
        and name not in options
    ]
    if unserved:
        raise CalibrationError(
            f"Forward model {getattr(model_cls, 'model_id', model_cls)!r} demands "
            f"{', '.join(unserved)}, and a model is built from {', '.join(CONSTRUCTION_OPTIONS)}. "
            "What a model needs beyond those it reads from the configuration it is handed, or "
            "gives a default."
        )
    arguments = {
        name: options[name]
        for name, parameter in parameters.items()
        if parameter.kind in bindable and name in options
    }
    return model_cls(**arguments)


def load_plugins(*, force: bool = False) -> int:
    """Register every conforming model declared in the entry-point group.

    Returns the number newly registered. A bad entry point is skipped with a
    warning naming what is wrong with it, never raised: one broken plugin must
    not take down a calibration that asked for a different model.
    """
    global _PLUGINS_LOADED
    if _PLUGINS_LOADED and not force:
        return 0

    count = 0
    try:
        declared = tuple(entry_points(group=ENTRY_POINT_GROUP))
    except Exception as exc:
        # The whole scan and not one entry point: unreadable distribution
        # metadata takes down ``importlib.metadata`` for every group at once,
        # and a run that asked for the built-in must not fall with it.
        logger.warning(
            "the %r entry-point group could not be scanned, so no plugin is registered: %s",
            ENTRY_POINT_GROUP,
            exc,
        )
        _PLUGINS_LOADED = True
        return 0
    for entry_point in declared:
        name = str(entry_point.name).strip()
        if not name:
            logger.warning(
                "forward model plugin %r ignored: its entry-point name is empty.", entry_point
            )
            continue
        if name in _BUILTIN_PATHS:
            logger.warning(
                "forward model plugin %r ignored: %r is a model this build ships. Answering "
                "under that name would make a calibration session record a model it did not "
                "run.",
                entry_point,
                name,
            )
            continue
        if name in _REGISTRY and not force:
            continue
        try:
            model_cls = entry_point.load()
        except Exception as exc:  # pragma: no cover - exercised with stub entry points
            logger.warning("failed to load forward model plugin %r: %s", entry_point, exc)
            continue
        if getattr(model_cls, "model_id", None) != name:
            logger.warning(
                "forward model plugin %r ignored: the entry-point name is %r while the class "
                "declares model_id=%r. The name is what a document writes and the model_id is "
                "what a session is stamped with; two words for one model is how the two start "
                "describing different things.",
                entry_point,
                name,
                getattr(model_cls, "model_id", None),
            )
            continue
        try:
            register(model_cls, replace=force)
        except (TypeError, ValueError) as exc:
            logger.warning("forward model plugin %r ignored: %s", entry_point, exc)
            continue
        count += 1
    _PLUGINS_LOADED = True
    return count


def unregister(model_id: str) -> None:
    """Drop one entry, built-in declaration included. Primarily for tests."""
    _REGISTRY.pop(model_id, None)
    _BUILTIN_PATHS.pop(model_id, None)


def _load_builtin(model_id: str) -> type | None:
    """Import and register the in-tree class for *model_id*, if there is one."""
    path = _BUILTIN_PATHS.get(model_id)
    if path is None:
        return None
    module_path, _, class_name = path.partition(":")
    try:
        module = importlib.import_module(module_path)
        model_cls = getattr(module, class_name)
    except Exception as exc:
        raise CalibrationError(
            f"{model_id!r} is declared by this build at {path!r} and cannot be loaded here: "
            f"{type(exc).__name__}: {exc}. The declaration is right and the installation is "
            "not, so this is fixed by repairing the environment, not by editing the document."
        ) from exc
    return register(model_cls, replace=True)


def _unusable_members(model_cls: type) -> tuple[str, ...]:
    """Return the port members *model_cls* has no usable value for.

    Wider than presence: a member bound to ``None`` passes ``hasattr`` and fails
    the first call.
    """
    return tuple(name for name in forward_model_members() if getattr(model_cls, name, None) is None)


def _name_of(candidate: object) -> str:
    return str(getattr(candidate, "__qualname__", candidate))


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

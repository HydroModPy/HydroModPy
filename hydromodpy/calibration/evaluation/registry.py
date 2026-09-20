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

import importlib
import inspect
from importlib.metadata import entry_points

from hydromodpy.calibration.evaluation.port import evaluator_members
from hydromodpy.core.exceptions import CalibrationError
from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)

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
it, and a gate derived from the source holds ``cli_runner`` to passing exactly
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
        "hydromodpy.calibration.evaluation.pipeline_evaluator:PipelineTrialEvaluator"
    ),
    "analytic_bowl": "hydromodpy.calibration.evaluation.analytic_bowl:AnalyticBowlEvaluator",
    "scored_forward_model": (
        "hydromodpy.calibration.evaluation.scored_forward:ScoredForwardEvaluator"
    ),
}
"""Dotted paths to the in-tree evaluator classes, imported on first lookup.

Format ``"<module>:<class>"``, the one the terrain, solver and data-source
registries already use, so the plugin surfaces of this repository read alike.
"""

_REGISTRY: dict[str, type] = {}
_PLUGINS_LOADED = False


def builtin_evaluator_ids() -> tuple[str, ...]:
    """Return the ids this build ships, sorted, plugins excluded."""
    return tuple(sorted(_BUILTIN_PATHS))


def list_evaluator_ids() -> tuple[str, ...]:
    """Return every id resolvable here, built-in and installed, sorted.

    Loads the plugin group, because the answer is wrong without it. Does not
    import a built-in: the path is the declaration, and the class behind one is
    only needed when somebody asks for it by name.
    """
    if not _PLUGINS_LOADED:
        load_plugins()
    return tuple(sorted(set(_REGISTRY) | set(_BUILTIN_PATHS)))


def is_registered(evaluator_id: str) -> bool:
    """Whether :func:`get` would resolve *evaluator_id* without raising."""
    return evaluator_id in list_evaluator_ids()


def register(evaluator_cls: type, *, replace: bool = False) -> type:
    """Register an evaluator class under the ``evaluator_id`` it declares.

    The id is read off the class and never passed in: a registration that could
    name the class something else is one that lets a calibration session's record
    and the document that asked for it disagree.

    Returns the class unchanged, so it can be used as a decorator.

    Raises
    ------
    TypeError
        When the class declares no usable ``evaluator_id``, or lacks one of the
        members :class:`~hydromodpy.calibration.evaluation.port.TrialEvaluator`
        requires.
    ValueError
        When the id is already taken and *replace* is not set.
    """
    evaluator_id = getattr(evaluator_cls, "evaluator_id", None)
    if not isinstance(evaluator_id, str) or not evaluator_id.strip():
        raise TypeError(
            f"{_name_of(evaluator_cls)!r} declares evaluator_id={evaluator_id!r} on the class, "
            "and a registry keyed on a name cannot hold an evaluator that has none. It is a "
            "ClassVar[str] in the port; a value computed per instance is not readable here."
        )
    missing = _unusable_members(evaluator_cls)
    if missing:
        raise TypeError(
            f"{_name_of(evaluator_cls)!r} cannot serve {evaluator_id!r}: it does not satisfy "
            f"the trial-evaluator port, missing or unusable {', '.join(missing)}. A search "
            "calls every one of them, so the gap would surface after the setup rather than here."
        )
    # Both mappings, and two lookups compared against ``None``.
    #
    # ``_BUILTIN_PATHS`` and not only ``_REGISTRY``, because an in-tree evaluator
    # is a declaration until the first lookup imports it: before that lookup its
    # id looks free, and a class could claim ``hydromodpy_pipeline`` silently,
    # become what every document naming no evaluator runs, and key -- through
    # resolve_id -- exactly like the pipeline it had displaced. The entry-point
    # loop already refused that name; a direct call is the same surface.
    #
    # Two lookups rather than ``a or b``, because a class is truthy unless its
    # metaclass says otherwise, and one that said otherwise would read as absent
    # and be displaced by the next registration -- on any id, not only this one.
    taken: object | None = _REGISTRY.get(evaluator_id)
    if taken is None:
        taken = _BUILTIN_PATHS.get(evaluator_id)
    if taken is not None and not replace:
        raise ValueError(
            f"A trial evaluator is already registered for {evaluator_id!r}: "
            f"{_name_of(taken)}. Pass replace=True to substitute it, which is a "
            "deliberate in-process substitution the cache key cannot see."
        )
    _REGISTRY[evaluator_id] = evaluator_cls
    return evaluator_cls


def get(evaluator_id: str | None = None) -> type:
    """Return the evaluator **class** registered under *evaluator_id*.

    ``None`` resolves :data:`DEFAULT_EVALUATOR_ID`, so a document with nothing to
    say about the evaluator says nothing. Resolution order is the cache, then the
    in-tree declaration, then one scan of the plugin group.

    Raises
    ------
    CalibrationError
        When no evaluator answers to that name.
    """
    wanted = DEFAULT_EVALUATOR_ID if evaluator_id is None else evaluator_id
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
        f"No trial evaluator is registered for {wanted!r}. This installation serves {known}. "
        f"A third-party evaluator joins that list through the {ENTRY_POINT_GROUP!r} "
        "entry-point group, without a patch to HydroModPy."
    )


def needs_prepared_model(evaluator_id: str | None = None) -> bool:
    """Whether the named evaluator requires HydroModPy's own trial context.

    Answered from the class, so a caller knows before running ``prepare_trials``
    -- which is the whole geographic, mesh and data prefix of the pipeline.

    No fallback, on purpose: :func:`register` refuses a class that does not carry
    the member, so every class :func:`get` can return has one. A default here
    would be unreachable code claiming a behaviour nothing can produce.
    """
    return bool(get(evaluator_id).needs_prepared_model)


def resolve_id(evaluator_id: str | None = None) -> str:
    """Return the id the class behind *evaluator_id* declares for itself.

    ``None`` and the default's own spelling resolve to one answer, which is what
    lets a record, a cache key or a report say which evaluator ran without
    depending on whether the document bothered to name it.
    """
    return str(get(evaluator_id).evaluator_id)


def create(evaluator_id: str | None = None, **options: object) -> object:
    """Build the evaluator registered under *evaluator_id*, binding what it names.

    Only the constructor parameters the class declares are bound, and every
    keyword a parameter can reach is -- keyword-only and positional-or-keyword
    alike. An option no parameter names never arrives, which is what keeps the
    runner from having to know that ``trial_ctx`` means everything to the
    in-tree evaluator and nothing to a surrogate.

    Raises
    ------
    CalibrationError
        From :func:`get`, when no evaluator answers to that name; or when the
        constructor demands a positional-only argument, which a keyword cannot
        fill.
    """
    evaluator_cls = get(evaluator_id)
    parameters = inspect.signature(evaluator_cls).parameters
    unfillable = [
        name
        for name, parameter in parameters.items()
        if parameter.kind is inspect.Parameter.POSITIONAL_ONLY
        and parameter.default is inspect.Parameter.empty
    ]
    if unfillable:
        raise CalibrationError(
            f"Evaluator {getattr(evaluator_cls, 'evaluator_id', evaluator_cls)!r} takes "
            f"{', '.join(unfillable)} positionally only, and it is built from named options. "
            "Declare them as keyword parameters."
        )
    bindable = (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    arguments = {
        name: options[name]
        for name, parameter in parameters.items()
        if parameter.kind in bindable and name in options
    }
    return evaluator_cls(**arguments)


def load_plugins(*, force: bool = False) -> int:
    """Register every conforming evaluator declared in the entry-point group.

    Returns the number newly registered. A bad entry point is skipped with a
    warning naming what is wrong with it, never raised: one broken plugin must
    not take down a calibration that asked for a different evaluator.
    """
    global _PLUGINS_LOADED
    if _PLUGINS_LOADED and not force:
        return 0

    count = 0
    try:
        declared = tuple(entry_points(group=ENTRY_POINT_GROUP))
    except Exception as exc:
        # Deliberately the whole scan and not one entry point: unreadable or
        # contradictory distribution metadata takes down ``importlib.metadata``
        # for every group at once, and a run that asked for the built-in must
        # not be taken down by a distribution it never named.
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
                "trial evaluator plugin %r ignored: its entry-point name is empty.", entry_point
            )
            continue
        if name in _BUILTIN_PATHS:
            logger.warning(
                "trial evaluator plugin %r ignored: %r is the evaluator this build ships and "
                "names as its default. Answering under that name would make a calibration "
                "session record a method it did not run.",
                entry_point,
                name,
            )
            continue
        if name in _REGISTRY and not force:
            continue
        try:
            evaluator_cls = entry_point.load()
        except Exception as exc:  # pragma: no cover - exercised with stub entry points
            logger.warning("failed to load trial evaluator plugin %r: %s", entry_point, exc)
            continue
        if getattr(evaluator_cls, "evaluator_id", None) != name:
            logger.warning(
                "trial evaluator plugin %r ignored: the entry-point name is %r while the class "
                "declares evaluator_id=%r. The name is what a document writes and the "
                "evaluator_id is what a session is stamped with; two words for one evaluator "
                "is how the two start describing different things.",
                entry_point,
                name,
                getattr(evaluator_cls, "evaluator_id", None),
            )
            continue
        try:
            register(evaluator_cls, replace=force)
        except (TypeError, ValueError) as exc:
            logger.warning("trial evaluator plugin %r ignored: %s", entry_point, exc)
            continue
        count += 1
    _PLUGINS_LOADED = True
    return count


def unregister(evaluator_id: str) -> None:
    """Drop one entry, built-in declaration included. Primarily for tests.

    The declaration goes too, otherwise the next :func:`get` lazy-loads the
    built-in straight back and the removal looks like it did nothing. A fixture
    that removes a built-in restores both mappings.
    """
    _REGISTRY.pop(evaluator_id, None)
    _BUILTIN_PATHS.pop(evaluator_id, None)


def _load_builtin(evaluator_id: str) -> type | None:
    """Import and register the in-tree class for *evaluator_id*, if there is one."""
    path = _BUILTIN_PATHS.get(evaluator_id)
    if path is None:
        return None
    module_path, _, class_name = path.partition(":")
    try:
        module = importlib.import_module(module_path)
        evaluator_cls = getattr(module, class_name)
    except Exception as exc:
        # Deliberately every exception and not ``ImportError``: a module that
        # fails at import time fails in whatever way its own imports do.
        raise CalibrationError(
            f"{evaluator_id!r} is declared by this build at {path!r} and cannot be loaded here: "
            f"{type(exc).__name__}: {exc}. The declaration is right and the installation is "
            "not, so this is fixed by repairing the environment, not by editing the document."
        ) from exc
    return register(evaluator_cls, replace=True)


def _unusable_members(evaluator_cls: type) -> tuple[str, ...]:
    """Return the port members *evaluator_cls* has no usable value for.

    Wider than presence: a member bound to ``None`` passes ``hasattr`` and fails
    the first call. A registry decides what gets built, so it is the place where
    "declared but unusable" has to be refused.
    """
    return tuple(name for name in evaluator_members() if getattr(evaluator_cls, name, None) is None)


def _name_of(candidate: object) -> str:
    return str(getattr(candidate, "__qualname__", candidate))


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

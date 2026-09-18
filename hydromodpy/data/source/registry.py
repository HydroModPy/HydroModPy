"""``source_id -> DataSource class``, and the surface a third party registers on.

What this is for, and why it arrives only now
---------------------------------------------
The port shipped without it on purpose: a selection point that resolves a name
nobody outside this repository can supply is decoration, which is what D34
refuses and what D117 said about this exact module. It arrives with the thing
that makes the name third-party -- the ``hydromodpy.data.source`` entry-point
group -- and with the first in-tree caller that used to answer the same
question with an ``if/elif`` on a string.

The dispatch it replaces existed in **three independent copies** for
hydrography alone: the chain of ``if source_cfg.source == ...`` in
``variables/hydrography/manager.py``, the tuple of names the stream-burn
resolver matched against, and the ``Literal`` of the config model. Three lists
of the same four words, and nothing made them agree.

No ``[project.entry-points]`` table, and that is D21
----------------------------------------------------
The group is the **out-of-tree** surface only. In-tree sources are declared
once, in :data:`_BUILTIN_PATHS`, and importing them is deferred to the first
lookup that needs one -- so resolving ``bdtopage`` pulls in neither the IGN
client nor xarray. Declaring them in ``pyproject.toml`` as well would give each
one a second name and a second source of truth, which is precisely how
``flow_modflownwt`` once minted a solver pair that had an adapter and no
extractor. ``pyproject.toml`` carries the comment that says so, and no table.

What is refused, and why each refusal is not paranoia
-----------------------------------------------------
- **A class that does not carry the port's class-level members** is refused by
  :func:`register`, naming them. The eight declarations are read by callers
  that never ask first -- ``extent_for`` reads ``extent_crs`` before any fetch
  runs -- so a class missing one fails in the middle of a job rather than at
  the edge.
- **An entry point whose name is not the ``source_id`` its class declares** is
  refused. The name is what a configuration file writes and the ``source_id``
  is what the result is stamped with: two words for one source is how a
  request and its provenance start describing different things.
- **A plugin that takes a built-in name** is refused. The ``data-fetch``
  description this build ships names ``bdtopage`` and publishes the exact shape
  the in-tree adapter accepts; a plugin quietly answering under that name would
  make a frozen, byte-gated document describe something else entirely.

``variables`` is not checked here, and cannot be
------------------------------------------------
Seven of the port's eight declarations are ``ClassVar`` and readable on the
class. ``variables`` is the instance's, for the reason D114 gave, so
``hasattr`` on a class is ``False`` for it by design. :func:`register`
therefore holds a class to :data:`~hydromodpy.data.source.port.CLASS_SOURCE_MEMBERS`
and the conformance suite holds an instance to the rest.
"""

from __future__ import annotations

import importlib
import inspect
from importlib.metadata import entry_points

from hydromodpy.core.exceptions import DataCapabilityError, DataRequestError
from hydromodpy.core.logging import get_logger
from hydromodpy.data.source.port import missing_class_members

logger = get_logger(__name__)

ENTRY_POINT_GROUP = "hydromodpy.data.source"
"""The out-of-tree plugin group. One entry point per source, named on its id."""

_BUILTIN_PATHS: dict[str, str] = {
    "bdtopage": "hydromodpy.data.source.bdtopage:BdTopageSource",
    "euhydro": "hydromodpy.data.source.euhydro:EuHydroSource",
    "hubeau-piezometry": "hydromodpy.data.source.hubeau_piezometry:HubeauPiezometrySource",
    "ign-bdalti": "hydromodpy.data.source.ign_dem:IgnDemSource",
    "osm": "hydromodpy.data.source.osm:OsmSource",
    "sim2-precipitation": "hydromodpy.data.source.sim2_precipitation:Sim2PrecipitationSource",
}
"""Dotted paths to the in-tree source classes, imported on first lookup.

The single declaration of what this build serves. Format ``"<module>:<class>"``,
the one the solver registry already uses, so the two plugin surfaces of this
repository read the same way.
"""

_REGISTRY: dict[str, type] = {}
_PLUGINS_LOADED = False


def builtin_source_ids() -> tuple[str, ...]:
    """Return the ids this build ships, sorted, plugins excluded.

    Separate from :func:`list_source_ids` because the two answer different
    questions. What a build **describes** is frozen package data; what a
    deployment **resolves** depends on what is installed beside it. A caller
    that needs the first -- the ``data-fetch`` declaration, whose published
    description is compared byte for byte -- must not read the second.
    """
    return tuple(sorted(_BUILTIN_PATHS))


def list_source_ids() -> tuple[str, ...]:
    """Return every id resolvable here, built-in and installed, sorted.

    Loads the plugin group, because the answer is wrong without it. Does not
    import a built-in: the paths are the declaration, and the class behind one
    is only needed when somebody asks for it by name.
    """
    if not _PLUGINS_LOADED:
        load_plugins()
    return tuple(sorted(set(_REGISTRY) | set(_BUILTIN_PATHS)))


def is_registered(source_id: str) -> bool:
    """Whether :func:`get` would resolve *source_id* without raising."""
    return source_id in list_source_ids()


def register(source_cls: type, *, replace: bool = False) -> type:
    """Register a source class under the ``source_id`` it declares.

    The id is read **off the class** and never passed in: a registration that
    could name the class something else is a registration that lets the record
    stamp and the request disagree.

    Returns the class unchanged, so it can be used as a decorator.

    Raises
    ------
    TypeError
        When the class declares no usable ``source_id``, or lacks one of
        :data:`~hydromodpy.data.source.port.CLASS_SOURCE_MEMBERS`.
    ValueError
        When the id is already taken and *replace* is not set.
    """
    source_id = getattr(source_cls, "source_id", None)
    if not isinstance(source_id, str) or not source_id.strip():
        raise TypeError(
            f"{_name_of(source_cls)!r} declares source_id={source_id!r} on the class, and a "
            "registry keyed on a name cannot hold a source that has none. It is a "
            "ClassVar[str] in the port; a value computed per instance is not readable here."
        )
    missing = missing_class_members(source_cls)
    if missing:
        raise TypeError(
            f"{_name_of(source_cls)!r} cannot serve {source_id!r}: it does not satisfy the "
            f"data-source port, missing {', '.join(missing)}. Every one of them is read by a "
            "caller that does not ask first, so the gap surfaces mid-fetch rather than here."
        )
    if source_id in _REGISTRY and not replace:
        raise ValueError(
            f"A data source is already registered for {source_id!r}: "
            f"{_name_of(_REGISTRY[source_id])}. Pass replace=True to substitute it."
        )
    _REGISTRY[source_id] = source_cls
    return source_cls


def get(source_id: str) -> type:
    """Return the source **class** registered under *source_id*.

    A class and not an instance, because what configures a source lives in its
    constructor (D115) and only the caller knows those values. Resolution order
    is the cache, then the in-tree declaration, then one scan of the plugin
    group: nothing is imported until a lookup needs it.

    Raises
    ------
    DataRequestError
        When no source answers to that name. A malformed request and not a
        source failure: the caller fixes it with the network down.
    """
    cls = _REGISTRY.get(source_id)
    if cls is not None:
        return cls
    cls = _load_builtin(source_id)
    if cls is not None:
        return cls
    if not _PLUGINS_LOADED:
        load_plugins()
        cls = _REGISTRY.get(source_id)
        if cls is not None:
            return cls
    known = ", ".join(sorted(set(_REGISTRY) | set(_BUILTIN_PATHS))) or "none"
    raise DataRequestError(
        f"No data source is registered for {source_id!r}. This installation serves {known}. "
        f"A third-party source joins that list through the {ENTRY_POINT_GROUP!r} "
        "entry-point group, without a patch to HydroModPy."
    )


def get_serving(source_id: str, payload_kind: str) -> type:
    """Return the class registered under *source_id*, of that payload kind only.

    Resolving a name and checking what it serves is one question, asked by two
    callers that both answer it before anything is built: the configuration
    model of a variable, which refuses a document, and the seam that builds a
    source from a section, which is handed duck-typed objects the model never
    saw.

    The kind is read off the **declaration**, so a source of the wrong shape is
    refused before its constructor runs and therefore long before its provider
    is contacted. Reading it off the answer instead is what let a DEM source
    named in a hydrography section start downloading France-wide archives.

    Raises
    ------
    DataRequestError
        When no source answers to that name, from :func:`get`.
    DataCapabilityError
        When one does and it serves another payload kind.
    """
    source_cls = get(source_id)
    declared = getattr(source_cls, "payload_kind", None)
    if declared != payload_kind:
        raise DataCapabilityError(
            f"Source {source_id!r} serves a {declared!r} payload, and this one accepts a "
            f"{payload_kind!r} payload. A source of another kind belongs to another "
            "variable, and asking it anyway would contact its provider before the answer "
            "could be refused."
        )
    return source_cls


def load_plugins(*, force: bool = False) -> int:
    """Register every conforming source declared in the entry-point group.

    Returns the number newly registered. A bad entry point is skipped with a
    warning naming what is wrong with it, never raised: one broken plugin must
    not take down a host that asked for a different source.
    """
    global _PLUGINS_LOADED
    if _PLUGINS_LOADED and not force:
        return 0

    count = 0
    try:
        declared = tuple(entry_points(group=ENTRY_POINT_GROUP))
    except Exception as exc:
        # The scan itself, not one entry point: unreadable or contradictory
        # distribution metadata takes down ``importlib.metadata`` for every
        # group at once. Same policy as a single bad plugin, one level up --
        # a host that asked for a built-in must not be taken down by a
        # distribution it never named.
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
            logger.warning("data source plugin %r ignored: its entry-point name is empty.", name)
            continue
        if name in _BUILTIN_PATHS:
            logger.warning(
                "data source plugin %r ignored: %r is a source this build ships and "
                "describes. Answering under that name would make the published "
                "description of data-fetch describe a different source.",
                entry_point,
                name,
            )
            continue
        if name in _REGISTRY and not force:
            continue
        try:
            source_cls = entry_point.load()
        except Exception as exc:  # pragma: no cover - exercised with stub entry points
            logger.warning("failed to load data source plugin %r: %s", entry_point, exc)
            continue
        declared = getattr(source_cls, "source_id", None)
        if declared != name:
            logger.warning(
                "data source plugin %r ignored: the entry-point name is %r while the class "
                "declares source_id=%r. The name is what a configuration writes and the "
                "source_id is what a result is stamped with; two words for one source is "
                "how the two start describing different things.",
                entry_point,
                name,
                declared,
            )
            continue
        try:
            register(source_cls, replace=force)
        except (TypeError, ValueError) as exc:
            logger.warning("data source plugin %r ignored: %s", entry_point, exc)
            continue
        count += 1
    _PLUGINS_LOADED = True
    return count


def build_from_section(source_cls: type, section: object) -> object:
    """Build *source_cls* from a configuration section, by parameter name.

    One rule, and it is the whole reason the ``if/elif`` could go: **a source is
    handed the section field its constructor names, and nothing else.** Every
    parameter a keyword can reach is bound -- keyword-only and
    positional-or-keyword -- so a section field a source does not ask for never
    arrives, and a constructor taking only ``**kwargs`` receives nothing at all
    because a bag names no field.

    Restricting this to keyword-only parameters was tried first and dropped:
    all six in-tree sources declare theirs behind a ``*``, so the narrower rule
    passed every gate while **silently dropping** the value of any third-party
    source that wrote ``def __init__(self, waterway_types=...)``. A rule that
    only works for the style this repository happens to use is not a plugin
    surface.

    A source whose parameters the section does not carry is built with its own
    defaults, which is the answer for a third-party source: the flat sections of
    this tree are closed models, so a plugin cannot add a field to one, and
    getting defaults is strictly better than being unreachable. Full
    configuration of an out-of-tree source is the ``data-fetch`` capability's
    job, where the request document carries it.

    ``tests/unit/data/test_hydrography_source_binding.py`` pins, per built-in
    source, which fields of ``[[data.hydrography.sources]]`` this binds -- the
    one place a silent mis-binding could hide.

    Raises
    ------
    DataRequestError
        When the constructor demands a positional-only argument. A section
        fills a parameter by name, so such a source cannot be built from one,
        and saying that is better than a ``TypeError`` about a missing
        positional.
    """
    bindable = (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    parameters = inspect.signature(source_cls).parameters
    unfillable = [
        name
        for name, parameter in parameters.items()
        if parameter.kind is inspect.Parameter.POSITIONAL_ONLY
        and parameter.default is inspect.Parameter.empty
    ]
    if unfillable:
        raise DataRequestError(
            f"Source {getattr(source_cls, 'source_id', source_cls)!r} takes "
            f"{', '.join(unfillable)} positionally only, and a configuration section fills a "
            "parameter by the name it carries. Declare them as keyword parameters."
        )
    arguments = {
        name: getattr(section, name)
        for name, parameter in parameters.items()
        if parameter.kind in bindable and hasattr(section, name)
    }
    return source_cls(**arguments)


def unregister(source_id: str) -> None:
    """Drop one entry, built-in declaration included. Primarily for tests.

    The declaration goes too, otherwise the next :func:`get` lazy-loads the
    built-in straight back and the removal looks like it did nothing. A fixture
    that removes a built-in restores both mappings.
    """
    _REGISTRY.pop(source_id, None)
    _BUILTIN_PATHS.pop(source_id, None)


def _load_builtin(source_id: str) -> type | None:
    """Import and register the in-tree class for *source_id*, if there is one.

    An id this build declares and cannot load is still an id this installation
    does not serve, so it leaves through :func:`get`'s own exception with the
    reason attached. The alternative is what it replaced: a
    ``ModuleNotFoundError`` from inside a configuration validator, which
    reaches a user as the exit code that means "this is a bug in HydroModPy".
    An adapter of this tree imports nothing heavier than the port today, and
    that is a property of today -- a GDAL or a 7z binding pulled in by a future
    one turns a broken environment into this path.
    """
    path = _BUILTIN_PATHS.get(source_id)
    if path is None:
        return None
    module_path, _, class_name = path.partition(":")
    try:
        module = importlib.import_module(module_path)
        source_cls = getattr(module, class_name)
    except Exception as exc:
        # Deliberately every exception and not ``ImportError``: a module that
        # fails at import time fails in whatever way its own imports do, and a
        # C extension refusing to initialise raises none of them.
        raise DataRequestError(
            f"{source_id!r} is declared by this build at {path!r} and cannot be loaded here: "
            f"{type(exc).__name__}: {exc}. The declaration is right and the installation is "
            "not, so this is fixed by repairing the environment, not by editing the request."
        ) from exc
    return register(source_cls, replace=True)


def _name_of(candidate: object) -> str:
    return str(getattr(candidate, "__qualname__", candidate))


__all__ = [
    "ENTRY_POINT_GROUP",
    "build_from_section",
    "builtin_source_ids",
    "get",
    "get_serving",
    "is_registered",
    "list_source_ids",
    "load_plugins",
    "register",
    "unregister",
]

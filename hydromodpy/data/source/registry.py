"""``source_id -> DataSource class``, and the surface a third party registers on.

A name in a request resolves here to a source class, so a source this repository
does not ship joins through the ``hydromodpy.data.source`` entry-point group and
no file of ``hydromodpy/`` imports one. The in-tree sources are declared once, in
:data:`_BUILTIN_PATHS`, and imported on the first lookup that needs one, so
resolving ``bdtopage`` pulls in neither the IGN client nor xarray. They are not
in ``[project.entry-points]``, because a second declaration would give each one a
second name and a second source of truth. Registration and lookup are those of
:class:`~hydromodpy.core.plugin_registry.PluginRegistry`: a class without the
port's class-level members, an entry point whose name is not the ``source_id`` its
class declares, and a plugin that takes a built-in name are all refused.
``variables`` is the instance's and is not checked here, so the conformance suite
holds an instance to it.
"""

from __future__ import annotations

import inspect

from hydromodpy.core.exceptions import DataCapabilityError, DataRequestError
from hydromodpy.core.plugin_registry import PluginRegistry
from hydromodpy.data.source.port import CLASS_SOURCE_MEMBERS

ENTRY_POINT_GROUP = "hydromodpy.data.source"
"""The out-of-tree plugin group. One entry point per source, named on its id."""

_BUILTIN_PATHS: dict[str, str] = {
    "bdtopage": "hydromodpy.data.variables.hydrography.apis.bdtopage:BdTopageSource",
    "euhydro": "hydromodpy.data.variables.hydrography.apis.euhydro:EuHydroSource",
    "osm": "hydromodpy.data.variables.hydrography.apis.osm:OsmSource",
}
"""Dotted paths to the in-tree source classes, imported on first lookup.

The single declaration of what this build serves. Format ``"<module>:<class>"``,
the one every registry of this repository uses.
"""


def _class_members() -> tuple[str, ...]:
    """Return the port members a source class carries before anybody builds one."""
    return CLASS_SOURCE_MEMBERS


data_sources = PluginRegistry(
    kind="data source",
    id_attributes=("source_id",),
    group=ENTRY_POINT_GROUP,
    builtin_paths=_BUILTIN_PATHS,
    members=_class_members,
    error=DataRequestError,
)
"""The data-source registry, with no default: a request always names its source.

``data_sources.get`` returns the class and not an instance, because what
configures a source lives in its constructor and only the caller knows those
values. An unknown name is a malformed request, so it raises
:class:`~hydromodpy.core.exceptions.DataRequestError` and the caller fixes it
with the network down.
"""


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
        When no source answers to that name, from ``data_sources.get``.
    DataCapabilityError
        When one does and it serves another payload kind.
    """
    source_cls = data_sources.get(source_id)
    declared = getattr(source_cls, "payload_kind", None)
    if declared != payload_kind:
        raise DataCapabilityError(
            f"Source {source_id!r} serves a {declared!r} payload, and this one accepts a "
            f"{payload_kind!r} payload. A source of another kind belongs to another "
            "variable, and asking it anyway would contact its provider before the answer "
            "could be refused."
        )
    return source_cls


def build_from_section(source_cls: type, section: object) -> object:
    """Build *source_cls* from a configuration section, by parameter name.

    One rule, and it is the whole reason the ``if/elif`` could go: **a source is
    handed the section field its constructor names, and nothing else.** Every
    parameter a keyword can reach is bound -- keyword-only and
    positional-or-keyword -- so a section field a source does not ask for never
    arrives, and a constructor taking only ``**kwargs`` receives nothing at all
    because a bag names no field.

    Restricting this to keyword-only parameters was tried first and dropped:
    all three in-tree sources declare theirs behind a ``*``, so the narrower rule
    passed every gate while **silently dropping** the value of any third-party
    source that wrote ``def __init__(self, waterway_types=...)``. A rule that
    only works for the style this repository happens to use is not a plugin
    surface.

    A source whose parameters the section does not carry is built with its own
    defaults, which is the answer for a third-party source: the flat sections of
    this tree are closed models, so a plugin cannot add a field to one, and
    getting defaults is strictly better than being unreachable. Full
    configuration of an out-of-tree source is the ``installed`` member of a
    data request, whose ``options`` reach its constructor.

    ``tests/unit/data/variables/hydrography/test_hydrography_source_binding.py`` pins, per built-in
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


__all__ = [
    "ENTRY_POINT_GROUP",
    "build_from_section",
    "data_sources",
    "get_serving",
]

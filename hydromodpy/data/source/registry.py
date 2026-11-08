"""``(section, source_id) -> DataSource class``, the surface a plugin registers on.

A key has two parts because the words the TOML writes are not unique: ``hubeau``
serves four variables, ``sim2`` nine. A source is registered under its
``section`` and its ``source_id``, joined by ``_``, and a section therefore
chooses its own sources and no others: a section of hydrography cannot reach the
DEM of the ``dem`` section, by construction rather than by a check of the
payload kind. A plugin joins through the ``hydromodpy.data.source`` entry-point
group, published under the same joined name, ``<section>_<source_id>``, exactly
the rule the solver backends follow; no file of ``hydromodpy/`` imports one. The
in-tree sources are declared once, in :data:`_BUILTIN_PATHS`, and imported on
the first lookup that needs one, so resolving ``hydrography_osm`` pulls in
neither the IGN client nor xarray. Registration and lookup are those of
:class:`~hydromodpy.core.plugin_registry.PluginRegistry`: a class without the
port's class-level members, an entry point whose name is not the id its class
declares, and a plugin that takes a built-in name are all refused. ``variables``
and ``hosts`` are the instance's and are not checked here, so the conformance
suite holds an instance to them.

A plugin source can also be asked for by its ``source_id`` alone, on the
``installed`` member of a data request; :func:`installed_source_cls` resolves
that name among the classes the group scanned, refusing an ambiguity by naming
the keys, because that is the one question a joined key cannot answer by itself.
"""

from __future__ import annotations

import inspect

from hydromodpy.core.exceptions import DataRequestError
from hydromodpy.core.plugin_registry import PluginRegistry
from hydromodpy.data.source.port import CLASS_SOURCE_MEMBERS

ENTRY_POINT_GROUP = "hydromodpy.data.source"
"""The out-of-tree plugin group. One entry point per source, named ``<section>_<source_id>``."""

_BUILTIN_PATHS: dict[str, str] = {
    "hydrography_bdtopage": "hydromodpy.data.variables.hydrography.apis.bdtopage:BdTopageSource",
    "hydrography_euhydro": "hydromodpy.data.variables.hydrography.apis.euhydro:EuHydroSource",
    "hydrography_osm": "hydromodpy.data.variables.hydrography.apis.osm:OsmSource",
    "hydrometry_hubeau": "hydromodpy.data.variables.hydrometry.apis.hubeau:HubeauHydrometry",
    "piezometry_hubeau": "hydromodpy.data.variables.piezometry.apis.hubeau:HubeauPiezometry",
    "water_quality_hubeau": (
        "hydromodpy.data.variables.water_quality.apis.hubeau:HubeauWaterQuality"
    ),
    "intermittency_hubeau": (
        "hydromodpy.data.variables.intermittency.apis.hubeau:HubeauIntermittency"
    ),
    "precipitation_sim2": "hydromodpy.data.common.clients.sim2_products:Sim2Precipitation",
    "etp_sim2": "hydromodpy.data.common.clients.sim2_products:Sim2Etp",
    "temperature_sim2": "hydromodpy.data.common.clients.sim2_products:Sim2Temperature",
    "wind_sim2": "hydromodpy.data.common.clients.sim2_products:Sim2Wind",
    "humidity_sim2": "hydromodpy.data.common.clients.sim2_products:Sim2Humidity",
    "radiation_sim2": "hydromodpy.data.common.clients.sim2_products:Sim2Radiation",
    "soil_moisture_sim2": "hydromodpy.data.common.clients.sim2_products:Sim2SoilMoisture",
    "runoff_sim2": "hydromodpy.data.common.clients.sim2_products:Sim2Runoff",
    "recharge_sim2": "hydromodpy.data.common.clients.sim2_products:Sim2Recharge",
    "precipitation_explore2": (
        "hydromodpy.data.common.clients.explore2_files:Explore2Precipitation"
    ),
    "etp_explore2": "hydromodpy.data.common.clients.explore2_files:Explore2Etp",
    "recharge_synthetic": "hydromodpy.data.variables.recharge.synthetic:SyntheticRecharge",
    "oceanic_shom": "hydromodpy.data.variables.oceanic.apis.shom:ShomSeaLevel",
    "oceanic_constant": "hydromodpy.data.variables.oceanic.constant:ConstantSeaLevel",
    "dem_ign_geoplateforme_dem": (
        "hydromodpy.data.variables.dem.apis.ign_dem_fr:IgnGeoplateformeDem"
    ),
    "geology_brgm_1m": "hydromodpy.data.variables.geology.apis.brgm_1m:Brgm1m",
    "geology_brgm_50k": "hydromodpy.data.variables.geology.apis.brgm_50k:Brgm50k",
    "crossings_bdtopo": "hydromodpy.data.variables.crossings.apis.bdtopo:BdTopoCrossings",
    "crossings_roe": "hydromodpy.data.variables.crossings.apis.roe:RoeCrossings",
}
"""Dotted paths to the in-tree source classes, imported on first lookup.

The single declaration of what this build serves: 26 sources under 18 sections.
Format ``"<module>:<class>"``, the one every registry of this repository uses.
"""


def _class_members() -> tuple[str, ...]:
    """Return the port members a source class carries before anybody builds one."""
    return CLASS_SOURCE_MEMBERS


data_sources = PluginRegistry(
    kind="data source",
    id_attributes=("section", "source_id"),
    group=ENTRY_POINT_GROUP,
    builtin_paths=_BUILTIN_PATHS,
    members=_class_members,
    error=DataRequestError,
)
"""The data-source registry, keyed on the two parts of a source's identity.

``data_sources.get("dem", "ign_geoplateforme_dem")`` and
``data_sources.get("dem_ign_geoplateforme_dem")`` resolve the same class, and
``data_sources.names("hydrometry")`` lists what a hydrometry section may name. A
lookup returns the class and not an instance, because what configures a source
lives in its constructor and only the caller knows those values, and a lookup
with no name has no default to answer. An unknown name is a malformed request,
so it raises :class:`~hydromodpy.core.exceptions.DataRequestError` and the
caller fixes it with the network down.
"""


def installed_source_cls(name: str) -> type:
    """Return the one plugin class whose ``source_id`` is *name*.

    An ``installed`` request names a plugin by its ``source_id``, the part a
    document can write without knowing which section a third party chose. The
    plugin group is scanned, then the classes it registered are filtered on
    their declared ``source_id``, excluding anything this build ships: a
    built-in stays reachable through its ``[data]`` section, which is the shore
    its options are described on.

    Raises
    ------
    DataRequestError
        When no plugin answers to that source id, or when several do. An
        ambiguity is refused **naming the keys**, because the id alone did not
        say which section was meant, and the keys do.
    """
    if not isinstance(name, str) or not name.strip():
        raise DataRequestError(f"An installed source is named by a source id, not by {name!r}.")
    if not data_sources.plugins_loaded:
        data_sources.load_plugins()
    candidates = {
        key: cls
        for key, cls in data_sources.classes.items()
        if key not in data_sources.builtin_paths and getattr(cls, "source_id", None) == name.strip()
    }
    if len(candidates) > 1:
        keys = ", ".join(f"{key!r}" for key in sorted(candidates))
        raise DataRequestError(
            f"Several installed sources answer to the source id {name!r}: {keys}. The id "
            "alone does not say which section was meant, so name one of these keys instead."
        )
    if candidates:
        return next(iter(candidates.values()))
    known = ", ".join(sorted(data_sources.names())) or "none"
    raise DataRequestError(
        f"No installed source answers to the source id {name!r}. This installation serves "
        f"{known}. A shipped source is asked for through its [data] section, and a "
        f"third-party one joins that list through the {ENTRY_POINT_GROUP!r} entry-point "
        "group, without a patch to HydroModPy."
    )


def build_from_section(source_cls: type, section: object, **resolved: object) -> object:
    """Build *source_cls* from a configuration section, by parameter name.

    One rule, and it is the whole reason the ``if/elif`` could go: **a source is
    handed the section field its constructor names, and nothing else.** Every
    parameter a keyword can reach is bound, keyword-only and
    positional-or-keyword alike, so a section field a source does not ask for
    never arrives, and a constructor taking only ``**kwargs`` receives nothing at
    all because a bag names no field.

    *resolved* carries what only the caller can compute, and each of its keys
    wins over a section field of the same name: the point a nearest-station
    search starts from is measured on the resolved extent, and a window the
    section writes as dates is bound as datetimes. A key no constructor
    parameter names is dropped, on the same rule a section field is: the source
    asks for what it reads.

    Restricting this to keyword-only parameters was tried first and dropped:
    every in-tree source declared its options behind a ``*``, so the narrower
    rule passed every gate while silently dropping the value of any third-party
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
    source, which fields of a section this binds: the one place a silent
    mis-binding could hide.

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
            f"{', '.join(unfillable)} positionally only, and a configuration section fills "
            "a parameter by the name it carries. Declare them as keyword parameters."
        )
    arguments = {
        name: getattr(section, name)
        for name, parameter in parameters.items()
        if parameter.kind in bindable and hasattr(section, name)
    }
    has_var_keyword = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values())
    if has_var_keyword:
        arguments.update(resolved)
    else:
        arguments.update(
            {
                k: v
                for k, v in resolved.items()
                if k in parameters and parameters[k].kind in bindable
            }
        )
    return source_cls(**arguments)


__all__ = [
    "ENTRY_POINT_GROUP",
    "build_from_section",
    "data_sources",
    "installed_source_cls",
]

"""The data-source port and the adapters that serve it.

``port`` holds the Protocol and its value types and imports nothing heavier
than the exception module, so a caller that only needs the vocabulary pulls in
neither geopandas, nor pandas, nor requests, nor pydantic. The adapters are
resolved lazily for the same reason, and each of them reaches its provider's
api module from inside ``fetch`` rather than at import time.

There is deliberately no source registry here. A selection point with no caller
is decoration -- the same reason the terrain port ships without one. It arrives
with the plugin surface that has to resolve a third-party name.
"""

from __future__ import annotations

from importlib import import_module

from hydromodpy.data.source.port import (
    ALL_PAYLOAD_KINDS,
    ALL_PERIOD_NEEDS,
    ALL_SELECTORS,
    SOURCE_MEMBERS,
    DataSource,
    Extent,
    FetchRequest,
    FetchResult,
    PayloadKind,
    Period,
    PeriodNeed,
    Selector,
    extent_for,
    missing_source_members,
    require_declared_variables,
    require_period,
    require_selectors,
)

__all__ = [
    "ALL_PAYLOAD_KINDS",
    "ALL_PERIOD_NEEDS",
    "ALL_SELECTORS",
    "SOURCE_MEMBERS",
    "BdTopageSource",
    "DataSource",
    "Extent",
    "FetchRequest",
    "FetchResult",
    "HubeauPiezometrySource",
    "IgnDemSource",
    "PayloadKind",
    "Period",
    "PeriodNeed",
    "Selector",
    "Sim2PrecipitationSource",
    "extent_for",
    "missing_source_members",
    "require_declared_variables",
    "require_period",
    "require_selectors",
]

_LAZY_IMPORTS = {
    "BdTopageSource": "hydromodpy.data.source.bdtopage:BdTopageSource",
    "HubeauPiezometrySource": "hydromodpy.data.source.hubeau_piezometry:HubeauPiezometrySource",
    "IgnDemSource": "hydromodpy.data.source.ign_dem:IgnDemSource",
    "Sim2PrecipitationSource": (
        "hydromodpy.data.source.sim2_precipitation:Sim2PrecipitationSource"
    ),
}


def __getattr__(name: str):
    try:
        target = _LAZY_IMPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    module_path, attr_name = target.split(":", 1)
    attr = getattr(import_module(module_path), attr_name)
    globals()[name] = attr
    return attr

"""Terrain port and the engines that serve it.

The port is importable without any flow-routing library: ``port`` holds the
Protocol and its value types and imports nothing heavier than the exception
module. The two engines are resolved lazily, so a caller that only needs the
vocabulary never pulls in ``whitebox_workflows``.

``registry`` is the selection point. It was refused here for as long as it had
no caller -- a selection point nothing selects through is decoration -- and it
arrived with the capability that has to choose one, ``terrain-delineate``. It
resolves the two engines of this tree and anything installed under the
``hydromodpy.terrain.engine`` entry-point group, and it certifies a candidate on
the members the port declares. That is all a registry can certify: the port also
requires artefacts on disk, and only
``tests/contract/test_terrain_engine_contract.py`` sees those. It is
parametrized on what the registry resolves, so it runs an outside engine without
naming it.
"""

from __future__ import annotations

from importlib import import_module

from hydromodpy.spatial.terrain.port import (
    D8_WBT_OFFSETS,
    DEFAULT_CATCHMENT_LAYOUT,
    LN_FLOAT32_COLLISION_COUNT,
    MASK_INSIDE,
    MASK_NODATA,
    OUTLET_LAYER_NAME,
    RANK_PRESERVING_TRANSFORMS,
    SNAPPED_OUTLET_LAYER_NAME,
    AccumulationTransform,
    AccumulationUnits,
    Catchment,
    CatchmentLayout,
    ConditionedDem,
    ConditioningExtent,
    ConditioningExtentKind,
    ConditioningMethod,
    DrainageDirections,
    FlowAccumulation,
    Outlet,
    PointerConvention,
    StreamNetwork,
    TerrainEngine,
    engine_members,
    missing_engine_members,
    require_batch,
    require_rank_preserving,
    require_resolvable_counts,
    require_untransformed,
    snap_window_cells,
)

__all__ = [
    "D8_WBT_OFFSETS",
    "DEFAULT_CATCHMENT_LAYOUT",
    "LN_FLOAT32_COLLISION_COUNT",
    "MASK_INSIDE",
    "MASK_NODATA",
    "OUTLET_LAYER_NAME",
    "RANK_PRESERVING_TRANSFORMS",
    "SNAPPED_OUTLET_LAYER_NAME",
    "AccumulationTransform",
    "AccumulationUnits",
    "Catchment",
    "CatchmentLayout",
    "ConditionedDem",
    "ConditioningExtent",
    "ConditioningExtentKind",
    "ConditioningMethod",
    "DrainageDirections",
    "FlowAccumulation",
    "NumpyTerrainEngine",
    "Outlet",
    "PointerConvention",
    "StreamNetwork",
    "TerrainEngine",
    "WhiteboxTerrainEngine",
    "engine_members",
    "missing_engine_members",
    "require_batch",
    "require_rank_preserving",
    "require_resolvable_counts",
    "require_untransformed",
    "snap_window_cells",
]

_LAZY_IMPORTS = {
    "NumpyTerrainEngine": "hydromodpy.spatial.terrain.numpy_engine:NumpyTerrainEngine",
    "WhiteboxTerrainEngine": "hydromodpy.spatial.terrain.whitebox_engine:WhiteboxTerrainEngine",
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

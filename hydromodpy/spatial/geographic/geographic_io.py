"""Shared I/O helpers for geographic processing."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd


def write_shapefile_without_duplicate_columns(src_path: str | Path, dst_path: str | Path) -> None:
    """Read a shapefile and write it back after dropping duplicate column names."""
    gdf = gpd.read_file(src_path)
    gdf = gdf.loc[:, ~gdf.columns.duplicated()]
    gdf.to_file(dst_path)


def resolve_delineation_backend(backend: object | None = None) -> object:
    """Return the injected backend or the default delineation registry entry."""
    if backend is not None:
        return backend
    from hydromodpy.spatial.delineation import get_backend

    return get_backend()


def backend_has_callables(backend: object, component_name: str, *method_names: str) -> bool:
    """Return true when one backend component exposes all named methods."""
    component = getattr(backend, component_name, None)
    if component is None:
        return False
    return all(callable(getattr(component, method_name, None)) for method_name in method_names)

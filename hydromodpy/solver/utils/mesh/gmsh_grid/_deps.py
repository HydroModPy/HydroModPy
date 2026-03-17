"""Lazy optional-dependency loaders for the gmsh_grid package."""

from __future__ import annotations


def require_meshio():
    """Import and return the ``meshio`` module, or raise a clear error."""
    try:
        import meshio  # type: ignore
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on environment
        raise ImportError(
            "meshio is required for Gmsh mesh read/write support. "
            "Install the 'meshio' package to use this feature."
        ) from exc
    return meshio


def require_pyvista():
    """Import and return ``pyvista``, or raise a clear error."""
    try:
        import pyvista as pv  # type: ignore
    except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
        raise ImportError(
            "PyVista is required for interactive 3D viewing. "
            "Install the optional 'viewer3d' dependencies to use this module."
        ) from exc
    return pv


def require_gmsh():
    """Import and return the ``gmsh`` module, or raise a clear error."""
    try:
        import gmsh  # type: ignore
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on environment
        raise ImportError(
            "gmsh is required for zone-conformal mesh generation. "
            "Install the 'gmsh' Python package to use this workflow."
        ) from exc
    return gmsh

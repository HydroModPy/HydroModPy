"""Lazy optional-dependency loaders for the ``gmsh_grid`` package.

The reusable mesh layer is designed so that light read-only use cases do not
need to import every heavy dependency upfront. These helpers make optional
imports explicit and provide clearer error messages than a raw
``ModuleNotFoundError`` would.
"""

from __future__ import annotations


def require_meshio():
    """Import and return ``meshio``.

    ``meshio`` is used for neutral mesh I/O and for writing/reading 3D prism
    meshes together with their metadata.
    """
    try:
        import meshio  # type: ignore
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on environment
        raise ImportError(
            "meshio is required for Gmsh mesh read/write support. "
            "Install the 'meshio' package to use this feature."
        ) from exc
    return meshio


def require_pyvista():
    """Import and return ``pyvista`` for optional interactive 3D viewing."""
    try:
        import pyvista as pv  # type: ignore
    except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
        raise ImportError(
            "PyVista is required for interactive 3D viewing. "
            "Install the optional 'viewer3d' dependencies to use this module."
        ) from exc
    return pv


def require_gmsh():
    """Import and return ``gmsh`` for zone-conformal mesh generation."""
    try:
        import gmsh  # type: ignore
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on environment
        raise ImportError(
            "gmsh is required for zone-conformal mesh generation. "
            "Install the 'gmsh' Python package to use this workflow."
        ) from exc
    return gmsh

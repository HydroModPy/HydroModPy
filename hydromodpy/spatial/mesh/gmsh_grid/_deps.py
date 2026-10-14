"""Lazy optional-dependency loaders for the ``gmsh_grid`` package.

The reusable mesh layer is designed so that light read-only use cases do not
need to import every heavy dependency upfront. These helpers make optional
imports explicit and provide clearer error messages than a raw
``ModuleNotFoundError`` would.
"""

from __future__ import annotations


def require_meshio():
    """Import and return ``meshio``.

    ``meshio`` is used for neutral mesh I/O.
    """
    try:
        import meshio
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on environment
        raise ImportError(
            "meshio is required for Gmsh mesh read/write support. "
            "Install the 'meshio' package to use this feature."
        ) from exc
    return meshio


def require_gmsh():
    """Import and return ``gmsh`` for mesh generation."""
    try:
        import gmsh
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on environment
        raise ImportError(
            "gmsh is required for mesh generation. "
            "Install the 'gmsh' Python package to use this workflow."
        ) from exc
    return gmsh

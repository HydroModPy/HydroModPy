"""Lazy ``meshio`` loader for the ``gmsh_grid`` package.

The reader imports ``meshio`` on demand, with a clearer error message than a raw
``ModuleNotFoundError`` would give. ``gmsh`` is imported by the triangle engine,
:func:`hydromodpy.spatial.mesh.engines.triangle.gmsh_cdt.require_gmsh`.
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

"""VTU read/write for ``HydroMesh``.

VTU (VTK Unstructured Grid XML) is the recommended portable disk format for
both structured and unstructured HydroModPy meshes because it is:

- widely supported (ParaView, PyVista, meshio, QGIS via plugins),
- self-describing (vertices, connectivity, cell types, data arrays),
- format-agnostic regarding 2D vs 3D, structured vs unstructured.

This module intentionally remains thin and delegates the actual conversion to
the ``meshio`` adapter layer.
"""

from __future__ import annotations

from pathlib import Path

from hydromodpy.spatial.mesh.hydro_mesh import HydroMesh


def _require_meshio():
    try:
        import meshio  # type: ignore
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise ImportError(
            "meshio is required for VTU I/O. Install it with: pip install meshio"
        ) from exc
    return meshio


def write_vtu(path: str | Path, hydro_mesh: HydroMesh) -> Path:
    """Write a ``HydroMesh`` to a VTU file and return the resolved path."""
    from hydromodpy.spatial.mesh.adapters.meshio_adapter import to_meshio

    meshio = _require_meshio()
    path_obj = Path(path).resolve()
    meshio_mesh = to_meshio(hydro_mesh)
    meshio.write(path_obj, meshio_mesh, file_format="vtu")
    return path_obj


def read_vtu(path: str | Path) -> HydroMesh:
    """Read a VTU file into a ``HydroMesh``."""
    from hydromodpy.spatial.mesh.adapters.meshio_adapter import from_meshio

    meshio = _require_meshio()
    path_obj = Path(path).resolve()
    meshio_mesh = meshio.read(path_obj)
    return from_meshio(meshio_mesh)

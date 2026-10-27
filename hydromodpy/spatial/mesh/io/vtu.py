"""VTU read/write for ``HydroMesh``.

VTU (VTK Unstructured Grid XML) is the recommended portable disk format for
both structured and unstructured HydroModPy meshes because it is:

- widely supported (ParaView, PyVista, meshio, QGIS via plugins),
- self-describing (vertices, connectivity, cell types, data arrays),
- format-agnostic regarding 2D vs 3D, structured vs unstructured.

This module intentionally remains thin and delegates the actual conversion to
``meshio_bridge``. A planar mesh is written with a zero z and reads back planar.

A file can carry values that belong to the whole mesh, such as its CRS, in the
``FieldData`` of the grid, which VTK, and so ParaView and PyVista, keep through
a load and a save. A number is an ``Int32`` array of one value. A text is its
UTF-8 bytes in a ``UInt8`` array. A VTK ``String`` array would show as text in
ParaView, but meshio refuses a whole file holding one, and meshio is how
HydroModPy and many scripts read a VTU.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from xml.etree import ElementTree

import meshio
import numpy as np

from hydromodpy.spatial.mesh.io.meshio_bridge import from_meshio, to_meshio
from hydromodpy.spatial.mesh.model.hydro_mesh import HydroMesh


def write_vtu(
    path: str | Path,
    hydro_mesh: HydroMesh,
    *,
    field_data: Mapping[str, str | int] | None = None,
) -> Path:
    """Write a ``HydroMesh`` to a VTU file and return the resolved path.

    ``field_data`` goes to the ``FieldData`` of the grid, in its order. An
    empty text is left out, since meshio cannot read an array of no value.
    """
    path_obj = Path(path).resolve()
    meshio_mesh = to_meshio(hydro_mesh)
    meshio.write(path_obj, meshio_mesh, file_format="vtu")
    if field_data:
        _write_field_data(path_obj, field_data)
    return path_obj


def read_vtu(path: str | Path) -> HydroMesh:
    """Read a VTU file into a ``HydroMesh``."""
    path_obj = Path(path).resolve()
    meshio_mesh = meshio.read(path_obj)
    return from_meshio(meshio_mesh)


def read_vtu_field_data(path: str | Path) -> dict[str, str | int | np.ndarray]:
    """Read the ``FieldData`` of a VTU file as :func:`write_vtu` writes it.

    A ``UInt8`` array reads as its UTF-8 text, an integer array of one value
    as that number, and any other array as it is.
    """
    values: dict[str, str | int | np.ndarray] = {}
    for name, array in meshio.read(Path(path).resolve()).field_data.items():
        array = np.asarray(array)
        if array.dtype == np.uint8:
            values[name] = bytes(array.reshape(-1)).decode("utf-8")
        elif array.dtype.kind == "i" and array.size == 1:
            values[name] = int(array.reshape(-1)[0])
        else:
            values[name] = array
    return values


def _write_field_data(path: Path, values: Mapping[str, str | int]) -> None:
    """Add ``values`` to the ``FieldData`` of the VTU meshio wrote at ``path``.

    meshio writes no ``FieldData``, so the block is added to its XML, ahead of
    the piece as VTK writes it.
    """
    block = ElementTree.Element("FieldData")
    for name, value in values.items():
        if isinstance(value, int) and not isinstance(value, bool):
            vtk_type, items = "Int32", [int(value)]
        else:
            vtk_type, items = "UInt8", list(str(value).encode("utf-8"))
        if not items:
            continue
        array = ElementTree.SubElement(
            block,
            "DataArray",
            {
                "type": vtk_type,
                "Name": name,
                "NumberOfTuples": str(len(items)),
                "format": "ascii",
            },
        )
        array.text = " ".join(str(item) for item in items)
    if not len(block):
        return
    tree = ElementTree.parse(path)
    tree.getroot().find("UnstructuredGrid").insert(0, block)
    tree.write(path, encoding="utf-8", xml_declaration=True)

"""Mesh engines and the cell mesh of HydroModPy.

A ``MeshRequest`` goes to one of the registered engines (``regular``,
``triangle``, ``voronoi``), which returns a ``PlanarCellMesh``: the cells, their
centres, the cell and face families, the zones, the identity and the QA. Every
consumer (forcings, properties, boundary conditions, solvers, storage) reads
that cell mesh, whatever the engine.

``HydroMesh`` is the plain vertex and cell-block container under it, used to
exchange or serialize a mesh.

The rule of thumb is:

- build a mesh through ``registry.create(engine).build(request)`` ;
- use ``HydroMesh`` to exchange or serialize meshes ;
- use adapters to bridge specialized representations ;
- use ``hydromodpy.spatial.mesh.plotting`` for quick QA plots ;
- use ``hydromodpy.spatial.mesh.io.vtu_io`` when a portable on-disk format is needed.

Quick start::

    from hydromodpy.spatial.mesh import HydroMesh, CellBlock, CellType

    mesh = HydroMesh(
        vertices=points_xy,
        cell_blocks=(CellBlock(CellType.TRIANGLE, connectivity),),
    )

Adapters::

    from hydromodpy.spatial.mesh.adapters import from_meshio, to_meshio
    from hydromodpy.spatial.mesh.adapters import (
        from_gmsh_planar,
        to_flopy_disv_args,
    )

Engines::

    from hydromodpy.spatial.mesh import MeshRequest, registry

    cell_mesh = registry.create("regular").build(request)

I/O::

    from hydromodpy.spatial.mesh.io import read_vtu, write_vtu

Plotting::

    from hydromodpy.spatial.mesh.plotting import plot_cell_values

More detailed usage notes and documentation entry points live in:

- ``hydromodpy/spatial/mesh/README.md`` (package map)
- ``docs/source/contribute/architecture/mesh/index.rst``
- ``docs/source/contribute/architecture/mesh/mesh-pivot.rst``
- ``docs/source/contribute/architecture/mesh/mesh-engines.rst``
"""

from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh
from hydromodpy.spatial.mesh.port import MeshEngine, MeshEngineCapabilities
from hydromodpy.spatial.mesh.request import (
    InputTriangulation,
    LineFamilySpec,
    MeshRequest,
    RasterGridSpec,
    SizeField,
)

__all__ = (
    "CellType",
    "CellBlock",
    "HydroMesh",
    "InputTriangulation",
    "LineFamilySpec",
    "MeshEngine",
    "MeshEngineCapabilities",
    "MeshRequest",
    "PlanarCellMesh",
    "RasterGridSpec",
    "SizeField",
)

"""Mesh engines and the cell mesh of HydroModPy.

A ``MeshRequest`` goes to one of the registered engines (``regular``,
``triangle``, ``voronoi``), which returns a ``PlanarCellMesh``: the cells, their
centres, the cell and face families, the zones, the identity and the QA. Every
consumer (forcings, properties, boundary conditions, solvers, storage) reads
that cell mesh, whatever the engine.

``HydroMesh`` is the plain vertex and cell-block container under it, used to
exchange or serialize a mesh.

The package re-exports nothing: each name is imported from the module that
defines it. The rule of thumb is:

- build a mesh through ``registry.create(engine).build(request)``, with the
  request of ``hydromodpy.spatial.mesh.request`` ;
- use ``HydroMesh`` (``model/hydro_mesh.py``) to exchange or serialize meshes ;
- use ``hydromodpy.spatial.mesh.io.vtu`` when a portable on-disk format is needed.

Quick start::

    from hydromodpy.spatial.mesh.model.cell_types import CellType
    from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh

    mesh = HydroMesh(
        vertices=points_xy,
        cell_blocks=(CellBlock(CellType.TRIANGLE, connectivity),),
    )

Engines::

    from hydromodpy.spatial.mesh import registry
    from hydromodpy.spatial.mesh.request import MeshRequest

    cell_mesh = registry.create("regular").build(request)

I/O::

    from hydromodpy.spatial.mesh.io.vtu import read_vtu, write_vtu

The package map is ``hydromodpy/spatial/mesh/README.md``. The architecture pages
live in ``docs/source/contribute/architecture/mesh/``.
"""

"""Mesh engines and the cell mesh of HydroModPy.

A ``MeshRequest`` goes to one of the registered engines (``regular``,
``triangle``, ``voronoi``), which returns a ``PlanarCellMesh``: the cells, their
centers, the cell and face families, the zones, the identity and the QA. Every
consumer (forcings, properties, boundary conditions, solvers, storage) reads
that cell mesh, whatever the engine.

``HydroMesh`` is the plain vertex and cell-block container under it, used to
exchange or serialize a mesh.

The package re-exports nothing: each name is imported from the module that
defines it. The rule of thumb is:

- build a mesh through ``registry.mesh_engines.create(engine).build(request)``, with the
  request of ``hydromodpy.mesh.request`` ;
- use ``HydroMesh`` (``planar/hydro_mesh.py``) to exchange or serialize meshes ;
- use ``hydromodpy.mesh.io.vtu`` when a portable on-disk format is needed.

Quick start::

    from hydromodpy.mesh.planar.cell_types import CellType
    from hydromodpy.mesh.planar.hydro_mesh import CellBlock, HydroMesh

    mesh = HydroMesh(
        vertices=points_xy,
        cell_blocks=(CellBlock(CellType.TRIANGLE, connectivity),),
    )

Engines::

    from hydromodpy.mesh import registry
    from hydromodpy.mesh.request import MeshRequest

    cell_mesh = registry.mesh_engines.create("regular").build(request)

I/O::

    from hydromodpy.mesh.io.vtu import read_vtu, write_vtu

The contract of the mesh port is ``hydromodpy/mesh/README.md``, and the steps and
folders of the package are told on its page of the developer docs, beside the
pages of ``docs/source/contribute/architecture/engines/``.
"""

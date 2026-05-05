StructuredGrid Class Diagram
============================

Scope
-----

This diagram isolates the static object model around FloPy
``StructuredGrid``.

It highlights:

- the HydroModPy domain objects that feed the builder,
- the narrow responsibility of ``StructuredGridBuilder``,
- the boundary between HydroModPy classes and the external FloPy grid,
- the downstream adapters that read ``StructuredGrid`` geometry.

Code map
--------

- ``hydromodpy/spatial/mesh/cartesian_grid/sgrid_from_config.py``:
  public entry point to grid creation from config.
- ``hydromodpy/spatial/mesh/cartesian_grid/sgrid_generation.py``:
  ``StructuredGridBuilder`` and geometric assembly.
- ``hydromodpy/spatial/mesh/cartesian_grid/sgrid_mesh_adapter.py``:
  downstream bridge from solver grid to field-style geometry.
- ``hydromodpy/solver/modflow_common/solver_mesh.py``:
  one solver-side consumer of the resolved mesh contract.

Recommended reading path
------------------------

1. ``hydromodpy/spatial/mesh/cartesian_grid/sgrid_from_config.py``
2. ``hydromodpy/spatial/mesh/cartesian_grid/sgrid_generation.py``
3. ``hydromodpy/spatial/mesh/cartesian_grid/sgrid_mesh_adapter.py``
4. ``hydromodpy/solver/modflow_common/solver_mesh.py``

Reading Guide
-------------

- ``-->`` means a stable relation or a produced object.
- ``..>`` means a transient usage or read dependency.
- The dynamic config-to-grid workflow is intentionally documented in a
  separate sequence view: :doc:`structured-grid-build-sequence-diagram`.

Diagram source
--------------

.. uml:: diagrams/structured_grid_class.wsd

.. literalinclude:: diagrams/structured_grid_class.wsd
   :language: text
   :caption: PlantUML (.wsd) source - StructuredGrid class diagram

Notes
-----

- ``StructuredGrid`` itself belongs to FloPy. The diagram focuses on the
  HydroModPy classes that prepare or consume it.
- ``SGridConfig``, ``RasterGridReader``, and ``PlanarDiscretizer`` are not
  shown here on purpose; they belong to the build sequence rather than to the
  core static structure.
- For the broader field discretization workflow built on top of the same grid,
  see :doc:`sgrid-fieldparam-discretization-diagrams`.

Related diagrams
----------------

- :doc:`structured-grid-build-sequence-diagram`
- :doc:`sgrid-fieldparam-discretization-diagrams`

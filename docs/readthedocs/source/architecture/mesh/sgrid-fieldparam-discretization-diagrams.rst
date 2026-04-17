SGrid and FieldParam Discretization Diagrams
============================================

Scope
-----

These diagrams describe how HydroModPy bridges:

- FloPy ``StructuredGrid`` (solver side),
- planar field meshes (field/geology side),
- ``Field``/``FieldParam`` value mapping for solver-ready arrays.

Code map
--------

- ``hydromodpy/solver/utils/mesh/cartesian_grid/sgrid_mesh_adapter.py``:
  geometry bridge from solver grid to field-side mesh logic.
- ``hydromodpy/solver/utils/mesh/cartesian_grid/sgrid_field_discretization.py``:
  field discretization helpers.
- ``hydromodpy/solver/utils/mesh/cartesian_grid/sgrid_fieldparam_discretization.py``:
  heterogeneous parameter mapping to solver arrays.
- ``hydromodpy/spatial/field/core/field_param.py``:
  upstream field-side parameter contract.

Recommended reading path
------------------------

1. ``hydromodpy/spatial/field/core/field_param.py``
2. ``hydromodpy/solver/utils/mesh/cartesian_grid/sgrid_mesh_adapter.py``
3. ``hydromodpy/solver/utils/mesh/cartesian_grid/sgrid_field_discretization.py``
4. ``hydromodpy/solver/utils/mesh/cartesian_grid/sgrid_fieldparam_discretization.py``

For a narrower static view centered on the solver grid itself, see
:doc:`structured-grid-class-diagram`.

Class Diagram
-------------

.. uml:: diagrams/sgrid_fieldparam_discretization_class.wsd

.. literalinclude:: diagrams/sgrid_fieldparam_discretization_class.wsd
   :language: text
   :caption: PlantUML (.wsd) source - SGrid/FieldParam discretization class diagram

Activity Diagram
----------------

.. uml:: diagrams/sgrid_fieldparam_discretization_activity.wsd

.. literalinclude:: diagrams/sgrid_fieldparam_discretization_activity.wsd
   :language: text
   :caption: PlantUML (.wsd) source - SGrid/FieldParam discretization activity diagram

Related diagrams
----------------

- :doc:`structured-grid-class-diagram`
- :doc:`../field/field-uml-diagrams`
- :doc:`../spatial_support/spatial-support-uml-diagrams`

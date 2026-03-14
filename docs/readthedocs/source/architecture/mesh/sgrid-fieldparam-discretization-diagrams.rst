SGrid and FieldParam Discretization Diagrams
============================================

Scope
-----

These diagrams describe how HydroModPy bridges:

- FloPy ``StructuredGrid`` (solver side),
- planar field meshes (field/geology side),
- ``Field``/``FieldParam`` value mapping for solver-ready arrays.

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

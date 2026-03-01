SGrid and FieldParam Discretization Diagrams
============================================

Scope
-----

These diagrams describe how HydroModPy bridges:

- FloPy ``StructuredGrid`` (solver side),
- planar field meshes (field/geology side),
- ``Field``/``FieldParam`` value mapping for solver-ready arrays.

Class Diagram
-------------

.. literalinclude:: diagrams/sgrid_fieldparam_discretization_class.wsd
   :language: text
   :caption: PlantUML (.wsd) source - SGrid/FieldParam discretization class diagram

Activity Diagram
----------------

.. literalinclude:: diagrams/sgrid_fieldparam_discretization_activity.wsd
   :language: text
   :caption: PlantUML (.wsd) source - SGrid/FieldParam discretization activity diagram

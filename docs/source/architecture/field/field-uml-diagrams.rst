Field UML Diagrams
==================

Scope
-----

These diagrams document class structure and typical runtime flows for
``hydromodpy.spatial.field``.

Code map
--------

- ``hydromodpy/spatial/field/core/field_spatial.py``:
  reusable field-side zone/value carrier.
- ``hydromodpy/spatial/field/core/field_param.py`` and
  ``field_param_config.py``:
  heterogeneous parameter contract consumed downstream by solvers.
- ``hydromodpy/spatial/field/meshes/``:
  concrete structured and triangular mesh implementations.
- ``hydromodpy/spatial/field/geology/``:
  geology-backed specializations built on the same field contract.

Recommended reading path
------------------------

1. ``hydromodpy/spatial/field/README.md``
2. ``hydromodpy/spatial/field/core/field_spatial.py``
3. ``hydromodpy/spatial/field/core/field_param.py``
4. one mesh implementation under ``hydromodpy/spatial/field/meshes/``
5. ``hydromodpy/spatial/field/cases/square/`` for a concrete runnable example

Core Class Diagram
------------------

This view is intentionally limited to the reusable ``field.core``
abstractions.

.. uml:: diagrams/field_classes.wsd

.. literalinclude:: diagrams/field_classes.wsd
   :language: text
   :caption: PlantUML (.wsd) source - field core class diagram

Square Case Relation Diagram
----------------------------

This view shows how the square example specializes the core abstractions and
which concrete mesh implementations it reuses.

.. uml:: diagrams/field_spatial_cases_classes.wsd

.. literalinclude:: diagrams/field_spatial_cases_classes.wsd
   :language: text
   :caption: PlantUML (.wsd) source - field square case relation diagram

Activity Diagram
----------------

.. uml:: diagrams/field_activity.wsd

.. literalinclude:: diagrams/field_activity.wsd
   :language: text
   :caption: PlantUML (.wsd) source - field activity diagram

Sequence Diagram
----------------

.. uml:: diagrams/field_sequence.wsd

.. literalinclude:: diagrams/field_sequence.wsd
   :language: text
   :caption: PlantUML (.wsd) source - field sequence diagram

Related diagrams
----------------

- :doc:`../spatial_support/spatial-support-uml-diagrams`
- :doc:`../mesh/sgrid-fieldparam-discretization-diagrams`

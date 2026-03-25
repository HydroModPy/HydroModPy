Field UML Diagrams
==================

Scope
-----

These diagrams document class structure and typical runtime flows for
``hydromodpy.spatial.field``.

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

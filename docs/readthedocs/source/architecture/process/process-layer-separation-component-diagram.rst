Process Layer Separation Component Diagram
==========================================

Scope
-----

This diagram highlights architectural boundaries between configuration,
runtime process objects, conceptual hydrology helpers, adapter logic, and
solver backends.

Diagram source
--------------

.. uml:: diagrams/process_layered_components.wsd

.. literalinclude:: diagrams/process_layered_components.wsd
   :language: text
   :caption: PlantUML (.wsd) source - process layer separation component diagram

Notes
-----

- Config parsing and validation are isolated from solver-specific code.
- Conceptual hydrology forcing remains outside ``hydromodpy.process`` and is
  exposed through the simulation forcing adapter layer.
- Runtime process classes are solver-agnostic containers.
- Adapter components are the only layer allowed to translate runtime data to
  solver input formats.

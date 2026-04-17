Process Layer Separation Component Diagram
==========================================

Scope
-----

This diagram highlights architectural boundaries between configuration,
runtime process objects, conceptual hydrology helpers, adapter logic, and
solver backends.

Code map
--------

- ``hydromodpy/process/prototype`` and ``contracts.py``:
  generic process-layer contracts.
- ``hydromodpy/process/flow`` and ``transport``:
  concrete runtime specializations.
- ``hydromodpy/process/hydrology`` and ``forcing``:
  conceptual forcing and hydrology helpers outside solver code.
- ``hydromodpy/simulation/adapters``:
  translation boundary.
- ``hydromodpy/solver``:
  backend-specific execution packages.

Recommended reading path
------------------------

1. ``hydromodpy/process/contracts.py``
2. ``hydromodpy/process/prototype/__init__.py``
3. ``hydromodpy/process/flow/__init__.py``
4. ``hydromodpy/process/forcing/__init__.py``
5. ``hydromodpy/simulation/adapters/registry.py``

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

Related diagrams
----------------

- :doc:`process-package-map`
- :doc:`process-runtime-to-solver-sequence-diagram`

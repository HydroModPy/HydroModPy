Process Layer Separation Component Diagram
==========================================

Scope
-----

This diagram highlights architectural boundaries between configuration,
runtime process objects, conceptual hydrology helpers, adapter logic, and
solver backends.

Code map
--------

- ``hydromodpy/physics/base`` and ``contracts.py``:
  generic process-layer contracts.
- ``hydromodpy/physics/flow`` and ``transport``:
  concrete runtime specializations.
- ``hydromodpy/physics/hydrology`` and ``forcing``:
  conceptual forcing and hydrology helpers outside solver code.
- ``hydromodpy/simulation/adapters``:
  translation boundary.
- ``hydromodpy/solver``:
  backend-specific execution packages.

Recommended reading path
------------------------

1. ``hydromodpy/physics/contracts.py``
2. ``hydromodpy/physics/base/__init__.py``
3. ``hydromodpy/physics/flow/__init__.py``
4. ``hydromodpy/physics/forcing/__init__.py``
5. ``hydromodpy/solver/base/registry.py``

Diagram source
--------------

.. uml:: diagrams/process_layered_components.wsd

.. literalinclude:: diagrams/process_layered_components.wsd
   :language: text
   :caption: PlantUML (.wsd) source - process layer separation component diagram

Notes
-----

- Config parsing and validation are isolated from solver-specific code.
- Conceptual hydrology forcing remains outside ``hydromodpy.physics`` and is
  exposed through the simulation forcing adapter layer.
- Runtime process classes are solver-agnostic containers.
- Adapter components are the only layer allowed to translate runtime data to
  solver input formats.

Related diagrams
----------------

- :doc:`process-package-map`
- :doc:`process-runtime-to-solver-sequence-diagram`

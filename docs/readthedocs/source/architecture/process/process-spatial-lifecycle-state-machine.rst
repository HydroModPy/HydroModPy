ProcessSpatial Lifecycle State Machine
======================================

Scope
-----

This state machine captures the usual lifecycle of a ``ProcessSpatial``-based
runtime object from creation to solver execution and post-processing.

Code map
--------

- ``hydromodpy/physics/base/process_spatial.py``:
  lifecycle root for process runtime objects.
- ``hydromodpy/physics/flow/structure_binders.py``:
  one example of hydration from domain and loaded data.
- ``hydromodpy/solver/<backend>/adapters/``:
  preparation boundary before solver calls.

Recommended reading path
------------------------

1. ``hydromodpy/physics/base/process_spatial.py``
2. ``hydromodpy/physics/flow/flow.py``
3. ``hydromodpy/physics/flow/structure_binders.py``
4. one adapter under ``hydromodpy/solver/<backend>/adapters/``

Diagram source
--------------

.. uml:: diagrams/process_spatial_lifecycle_state.wsd

.. literalinclude:: diagrams/process_spatial_lifecycle_state.wsd
   :language: text
   :caption: PlantUML (.wsd) source - ProcessSpatial lifecycle state machine

Notes
-----

- ``RuntimeHydrated`` means parameters, IC, BC, and sinks/sources are set.
- ``PreparedForSolver`` represents adapter-resolved arrays/dictionaries.
- Failures can route back to hydration after config or data corrections.

Related diagrams
----------------

- :doc:`process-runtime-class-diagram`
- :doc:`process-runtime-to-solver-sequence-diagram`

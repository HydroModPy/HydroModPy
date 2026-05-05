Process Extension Activity Diagram
==================================

Scope
-----

This activity diagram proposes a practical workflow to add a new
``ProcessSpatial`` specialization in HydroModPy.

Code map
--------

- ``hydromodpy/process/prototype``:
  base config and runtime contracts to extend.
- ``hydromodpy/process/flow``:
  current concrete specialization to copy for structure.
- ``hydromodpy/simulation/adapters``:
  required integration point after the runtime class exists.
- ``hydromodpy/solver/compatibility.py``:
  planner-facing compatibility declaration for new process/solver pairs.

Recommended reading path
------------------------

1. ``hydromodpy/process/prototype/process_spatial_config.py``
2. ``hydromodpy/process/prototype/process_spatial.py``
3. ``hydromodpy/process/flow/`` as the main concrete example
4. ``hydromodpy/solver/base/registry.py``
5. ``hydromodpy/solver/compatibility.py``

Diagram source
--------------

.. uml:: diagrams/process_extension_activity.wsd

.. literalinclude:: diagrams/process_extension_activity.wsd
   :language: text
   :caption: PlantUML (.wsd) source - process extension activity diagram

Notes
-----

- The flow follows config model first, then runtime class, then adapters.
- Testing and documentation updates are treated as mandatory completion steps.
- Iteration is expected before final integration.

Related diagrams
----------------

- :doc:`process-config-class-diagram`
- :doc:`process-layer-separation-component-diagram`
- :doc:`../overview/tests-and-validation`

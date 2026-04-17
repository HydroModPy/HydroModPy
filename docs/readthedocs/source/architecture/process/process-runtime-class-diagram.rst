Process Runtime Class Diagram
=============================

Scope
-----

This diagram shows runtime inheritance and composition for process objects:

- ``ProcessSpatial`` as the abstract runtime base.
- ``Flow`` and ``Transport`` as concrete process implementations.
- Runtime initial conditions, boundary conditions, and sink/source containers.

Code map
--------

- ``hydromodpy/process/prototype/process_spatial.py``:
  abstract runtime base.
- ``hydromodpy/process/flow/flow.py``:
  concrete flow runtime object.
- ``hydromodpy/process/transport/transport.py``:
  concrete transport runtime object.
- ``hydromodpy/process/prototype/*``:
  shared initial-condition, boundary-condition, and sink/source contracts.

Recommended reading path
------------------------

1. ``hydromodpy/process/prototype/process_spatial.py``
2. ``hydromodpy/process/flow/flow.py``
3. ``hydromodpy/process/transport/transport.py``
4. one prototype payload file under ``hydromodpy/process/prototype/``

Diagram source
--------------

.. uml:: diagrams/process_runtime_class.wsd

.. literalinclude:: diagrams/process_runtime_class.wsd
   :language: text
   :caption: PlantUML (.wsd) source - process runtime class diagram

Notes
-----

- ``Flow`` and ``Transport`` both inherit from ``ProcessSpatial``.
- ``FlowInitialCondition`` inherits from prototype ``InitialCondition``.
- Runtime boundary conditions stored by ``ProcessSpatial`` use prototype ``BoundaryCondition``.
- Runtime sink/source storage is generic (``dict[str, object]``), with process-specific payloads
  injected by child classes.
- Recharge chronicle preparation stays outside this inheritance tree and is
  handled by simulation forcing services before solver assembly.

Related diagrams
----------------

- :doc:`process-config-class-diagram`
- :doc:`process-runtime-to-solver-sequence-diagram`
- :doc:`process-package-map`

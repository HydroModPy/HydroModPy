Process Package Map
===================

Scope
-----

This page is the code-oriented entry point for ``hydromodpy.process``.

It is useful when you want to understand:

- where generic process contracts live,
- where ``Flow`` and ``Transport`` become concrete business objects,
- where forcing series are transformed into process-ready inputs,
- how the process layer connects simulation orchestration to solver backends.

Package map
-----------

The current ``hydromodpy.process`` stack is split into six distinct concerns:

- ``hydromodpy.process``:
  public compatibility facade that re-exports the main process symbols.
- ``hydromodpy.process.contracts``:
  explicit import path for generic process-layer contracts reused internally.
- ``hydromodpy.process.prototype``:
  process-agnostic building blocks such as ``ProcessSpatial``,
  ``ProcessSpatialConfig``, ``InitialCondition``, ``BoundaryCondition``, and
  ``SinkSource``.
- ``hydromodpy.process.flow``:
  concrete flow process object plus typed flow config and payload models.
- ``hydromodpy.process.transport``:
  concrete transport process object plus typed transport config.
- ``hydromodpy.process.forcing``:
  helpers that turn loaded data into process-ready forcing payloads aligned to
  simulation time.
- ``hydromodpy.process.hydrology``:
  hydrological utilities, synthetic forcing helpers, and the ``pyhelp``
  coupling stack.

Recommended reading paths
-------------------------

Generic process contracts
^^^^^^^^^^^^^^^^^^^^^^^^^

When the question is "what is the shared contract behind process objects?":

1. ``hydromodpy/process/contracts.py``
2. ``hydromodpy/process/prototype/__init__.py``
3. the files under ``hydromodpy/process/prototype/``

Flow process
^^^^^^^^^^^^

When the question is "what does the launcher materialize before a flow solve?":

1. ``hydromodpy/process/flow/__init__.py``
2. ``hydromodpy/process/flow/flow.py``
3. ``hydromodpy/process/flow/flow_config.py``
4. initial/boundary/sinks-source payload files under the same package

Transport process
^^^^^^^^^^^^^^^^^

When the question is "what transport runtime object is passed to the adapter?":

1. ``hydromodpy/process/transport/transport.py``
2. ``hydromodpy/process/transport/transport_config.py``

Forcing bridge
^^^^^^^^^^^^^^

When the question is "how do loaded data become solver-ready time series?":

1. ``hydromodpy/process/forcing/forcing_bridge.py``
2. ``hydromodpy/process/forcing/time_alignment.py``

Runtime role in the full stack
------------------------------

The process layer is intentionally between two other layers:

- launchers and the simulation runner materialize and carry ``Flow`` and
  ``Transport`` objects,
- solver adapters read those process objects and translate them into concrete
  backend calls.

In other words:

- ``process`` defines the hydrological problem payloads,
- ``simulation`` decides when those payloads are executed,
- ``solver`` decides how they are numerically solved.

What this section complements
-----------------------------

The UML pages in this section remain the best view for class and lifecycle
diagrams. This page instead provides the code-reading map that was previously
missing for the package.

See also
--------

- :doc:`process-runtime-class-diagram`
- :doc:`process-runtime-to-solver-sequence-diagram`
- :doc:`../simulation/toml-to-solver-walkthrough`

Process architecture
====================

This page is the code-oriented entry point for ``hydromodpy.model``,
the layer that turns validated configuration into the runtime
``Flow`` and ``Transport`` objects consumed by solver adapters.

It groups the package map, the reusable contracts, the runtime data
model, and every UML diagram (component, class, sequence, lifecycle,
extension) in one place.

Package map
-----------

The current ``hydromodpy.model`` package is split into six concerns.
No package file exports a name: each name is imported from the module
that defines it.

- ``hydromodpy.model.contracts``: explicit import path for generic
  process-layer contracts reused internally.
- ``hydromodpy.model.process_spatial``, ``hydromodpy.model.payloads`` and
  ``hydromodpy.model.forcing.dated_forcing``: process-agnostic building
  blocks (``ProcessSpatial``, ``InitialCondition``, ``BoundaryCondition``,
  ``SinkSource``, ``TimeSeriesForcing``).
- ``hydromodpy.model.flow``, ``hydromodpy.model.flow_config``,
  ``hydromodpy.model.initial_config`` and the folders ``boundaries`` and
  ``sinks_sources``: concrete flow process plus typed config and payload
  models.
- ``hydromodpy.model.model`` and the folder ``initial``: the frozen ``Model``
  a flow solver reads, its factories, and the five initial states.
- ``hydromodpy.model.transport``: concrete transport process plus
  typed config.
- ``hydromodpy.model.forcing``: helpers that turn loaded data into
  process-ready forcing payloads aligned to simulation time, and put
  gridded forcings on the cells of a mesh.
- ``hydromodpy.model.soil``: the arithmetic of the daily soil reservoir that
  makes a recharge from the weather. Its run on the loaded grids is in
  ``hydromodpy.model.forcing`` (``soil_*.py``).

Runtime role:

- ``model`` defines the hydrological problem payloads, and freezes them into
  a ``Model`` in ``prepare_solver``,
- ``solver`` decides when those payloads are executed (``solver/base/runner.py``)
  and how they are numerically solved.

Reading paths by concern
------------------------

**Generic process contracts** ("what is the shared contract behind
process objects?"):

1. ``hydromodpy/model/contracts.py``
2. ``hydromodpy/model/process_spatial.py``
3. ``hydromodpy/model/payloads.py``

**Flow process** ("what does the project materialize before a flow
solve?"):

1. ``hydromodpy/model/flow.py``
2. ``hydromodpy/model/flow_config.py``
3. initial / boundary / sinks-source payload files in
   ``hydromodpy/model/initial_config.py``, ``boundaries/`` and ``sinks_sources/``
4. ``hydromodpy/model/model.py``, the frozen ``Model`` that
   ``prepare_solver`` builds from the ``Flow`` and that a solver reads

**Transport process** ("what transport runtime object is passed to
the adapter?"):

1. ``hydromodpy/model/transport/transport.py``
2. ``hydromodpy/model/transport/transport_config.py``

**Forcing** ("how do loaded data become solver-ready time series?"):

1. ``hydromodpy/model/forcing/forcing_bridge.py`` (``resolve_forcing``)
2. ``hydromodpy/model/forcing/time_alignment.py``
3. ``hydromodpy/model/boundaries/`` (the ``apply_*_to_flow``
   functions of ``climate.py``, ``lakes.py``, ``streams.py`` and ``barriers.py``)

**Adding a new process**: see :doc:`../how-to/add-a-process`.

Layer separation (component diagram)
------------------------------------

Architectural boundaries between configuration, runtime process
objects, conceptual hydrology helpers, adapter logic, and solver
backends.

.. uml:: diagrams/process_layered_components.wsd

Notes:

- Config parsing and validation are isolated from solver-specific
  code.
- The forcing helpers and the binders fill the process objects from the loaded data.
- Runtime process classes are solver-agnostic containers.
- A flow adapter reads the frozen ``Model``, never the ``Flow``, the
  configuration or the geographic object.
- Adapter components are the only layer allowed to translate runtime
  data to solver input formats.

Config class diagram
--------------------

Validated configuration classes (Pydantic models): ``FlowConfig`` and
``TransportConfig``, flow-specific initial conditions, boundary
conditions, and sink/source configs.

.. uml:: diagrams/process_config_class.wsd

Notes:

- ``FlowConfig`` and ``TransportConfig`` share no base beyond ``HydroModelBase``.
- ``FlowInitialCondition`` inherits from prototype
  ``InitialCondition``.
- ``FlowBoundaryConditionConfig`` and ``FlowSinksSourcesConfig`` are
  dedicated flow models (not subclasses of prototype
  ``BoundaryCondition`` / ``SinkSource``).
- ``TransportConfig`` holds one block per transport solver (``modpath``, ``mt3dms``,
  ``modflow6gwt``, ``modflow6prt``). Its inherited generic containers are excluded from
  serialization.

Runtime class diagram
---------------------

Runtime inheritance and composition for process objects:
``ProcessSpatial`` as the abstract runtime base, ``Flow`` and
``Transport`` as concrete implementations, runtime initial
conditions, boundary conditions, and sink/source containers. The
frozen ``Model`` is drawn beside ``Flow``: ``model_from_flow`` builds it.

.. uml:: diagrams/process_runtime_class.wsd

Notes:

- ``Flow`` and ``Transport`` both inherit from ``ProcessSpatial``.
- ``FlowInitialCondition`` inherits from prototype
  ``InitialCondition``.
- Runtime boundary conditions stored by ``ProcessSpatial`` use
  prototype ``BoundaryCondition``.
- Runtime sink/source storage is generic (``dict[str, object]``),
  with process-specific payloads injected by child classes.
- Recharge and ETP are bound to the ``Flow`` by the binders, outside this inheritance
  tree.

Lifecycle state machine
-----------------------

The usual lifecycle of a ``ProcessSpatial``-based runtime object,
from creation to solver execution and post-processing.

.. uml:: diagrams/process_spatial_lifecycle_state.wsd

Notes:

- The states are a reading aid, not classes of the code. "Hydrated" means that
  parameters, initial conditions, boundary conditions and sinks and sources are set, and
  "prepared for solver" means that the adapter resolved its arrays and dictionaries.
- Failures can route back to hydration after config or data corrections.

Runtime-to-solver sequence
--------------------------

The main runtime handoff from process objects to solver backends: construction of
``Flow`` from the validated config, the binders that fill it from the loaded data,
adapter-level translation into solver payloads, and backend-specific execution.

.. uml:: diagrams/runtime_to_solver_sequence.wsd

Notes:

- The sequence is logical and backend-agnostic at the high level.
- Payload conversion is separated from the process runtime state.
- Forcing is resolved to one value per stress period before the adapter runs.
- Solver backends consume already-normalized process data.
- For the DIS payload semantics, see :doc:`../solver/backends`.

See also
--------

- :doc:`../simulation/toml-to-solver-walkthrough` for the
  configuration-to-solver path that consumes process objects.
- :doc:`../solver/backends` for the backend-side architecture.
- :doc:`../how-to/add-a-process` to add a process.
- :doc:`/contribute/project/tests` for the test expectations on a new process and
  solver pair.

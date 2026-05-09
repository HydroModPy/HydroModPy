Process Architecture
====================

This page is the code-oriented entry point for ``hydromodpy.physics``,
the layer that turns validated configuration into the runtime
``Flow`` and ``Transport`` objects consumed by solver adapters.

It groups the package map, the reusable contracts, the runtime data
model, and every UML diagram (component, class, sequence, lifecycle,
extension) in one place.

Package map
-----------

The current ``hydromodpy.physics`` stack is split into six concerns:

- ``hydromodpy.physics``: public compatibility facade that re-exports
  the main process symbols.
- ``hydromodpy.physics.contracts``: explicit import path for generic
  process-layer contracts reused internally.
- ``hydromodpy.physics.prototype``: process-agnostic building blocks
  (``ProcessSpatial``, ``ProcessSpatialConfig``,
  ``InitialCondition``, ``BoundaryCondition``, ``SinkSource``).
- ``hydromodpy.physics.flow``: concrete flow process plus typed
  config and payload models.
- ``hydromodpy.physics.transport``: concrete transport process plus
  typed config.
- ``hydromodpy.physics.forcing``: helpers that turn loaded data into
  process-ready forcing payloads aligned to simulation time.
- ``hydromodpy.physics.hydrology``: hydrological utilities, synthetic
  forcing helpers, and the ``pyhelp`` coupling stack.

Runtime role:

- ``physics`` defines the hydrological problem payloads,
- ``simulation`` decides when those payloads are executed,
- ``solver`` decides how they are numerically solved.

Reading paths by concern
------------------------

**Generic process contracts** ("what is the shared contract behind
process objects?"):

1. ``hydromodpy/process/contracts.py``
2. ``hydromodpy/process/prototype/__init__.py``
3. files under ``hydromodpy/process/prototype/``

**Flow process** ("what does the project materialize before a flow
solve?"):

1. ``hydromodpy/process/flow/__init__.py``
2. ``hydromodpy/process/flow/flow.py``
3. ``hydromodpy/process/flow/flow_config.py``
4. initial / boundary / sinks-source payload files in the same
   package

**Transport process** ("what transport runtime object is passed to
the adapter?"):

1. ``hydromodpy/process/transport/transport.py``
2. ``hydromodpy/process/transport/transport_config.py``

**Forcing bridge** ("how do loaded data become solver-ready time
series?"):

1. ``hydromodpy/process/forcing/forcing_bridge.py``
2. ``hydromodpy/process/forcing/time_alignment.py``

**Adding a new process** (extension workflow): see the activity
diagram below.

Layer separation (component diagram)
------------------------------------

Architectural boundaries between configuration, runtime process
objects, conceptual hydrology helpers, adapter logic, and solver
backends.

.. uml:: diagrams/process_layered_components.wsd

Notes:

- Config parsing and validation are isolated from solver-specific
  code.
- Conceptual hydrology forcing remains outside ``hydromodpy.physics``
  and is exposed through the simulation forcing adapter layer.
- Runtime process classes are solver-agnostic containers.
- Adapter components are the only layer allowed to translate runtime
  data to solver input formats.

Config class diagram
--------------------

Validated configuration classes (Pydantic models): shared
``ProcessSpatialConfig`` base, ``FlowConfig`` and ``TransportConfig``
specialisations, flow-specific initial conditions, boundary
conditions, and sink/source configs.

.. uml:: diagrams/process_config_class.wsd

Notes:

- ``FlowConfig`` and ``TransportConfig`` inherit from
  ``ProcessSpatialConfig``.
- ``FlowInitialCondition`` inherits from prototype
  ``InitialCondition``.
- ``FlowBoundaryConditionConfig`` and ``FlowSinksSourcesConfig`` are
  dedicated flow models (not subclasses of prototype
  ``BoundaryCondition`` / ``SinkSource``).
- ``TransportConfig`` currently keeps boundary and sink/source
  payloads as generic mappings.

Runtime class diagram
---------------------

Runtime inheritance and composition for process objects:
``ProcessSpatial`` as the abstract runtime base, ``Flow`` and
``Transport`` as concrete implementations, runtime initial
conditions, boundary conditions, and sink/source containers.

.. uml:: diagrams/process_runtime_class.wsd

Notes:

- ``Flow`` and ``Transport`` both inherit from ``ProcessSpatial``.
- ``FlowInitialCondition`` inherits from prototype
  ``InitialCondition``.
- Runtime boundary conditions stored by ``ProcessSpatial`` use
  prototype ``BoundaryCondition``.
- Runtime sink/source storage is generic (``dict[str, object]``),
  with process-specific payloads injected by child classes.
- Recharge chronicle preparation stays outside this inheritance tree
  and is handled by simulation forcing services before solver
  assembly.

Lifecycle state machine
-----------------------

The usual lifecycle of a ``ProcessSpatial``-based runtime object,
from creation to solver execution and post-processing.

.. uml:: diagrams/process_spatial_lifecycle_state.wsd

Notes:

- ``RuntimeHydrated`` means parameters, IC, BC, and sinks/sources are
  set.
- ``PreparedForSolver`` represents adapter-resolved arrays /
  dictionaries.
- Failures can route back to hydration after config or data
  corrections.

Runtime-to-solver sequence
--------------------------

The main runtime handoff from process objects to solver backends:
runtime construction of ``Flow`` from validated config, recharge
chronicle preparation before solver assembly, adapter-level
transformation into solver payloads, and backend-specific execution.

.. uml:: diagrams/runtime_to_solver_sequence.wsd

Notes:

- The sequence is logical and backend-agnostic at the high level.
- Payload conversion is explicitly separated from process runtime
  state.
- Recharge forcing is prepared before solver assembly and injected as
  already-aligned series.
- Solver wrappers remain consumers of already-normalised process
  data.
- For detailed DIS payload semantics, see
  :doc:`../modflow_contracts`.

Extending with a new process
----------------------------

Practical workflow to add a new ``ProcessSpatial`` specialisation:
config model first, then runtime class, then adapters. Testing and
documentation updates are mandatory completion steps; iteration is
expected before final integration.

Reading path before extending:

1. ``hydromodpy/process/prototype/process_spatial_config.py``
2. ``hydromodpy/process/prototype/process_spatial.py``
3. ``hydromodpy/process/flow/`` as the main concrete example
4. ``hydromodpy/solver/base/registry.py``
5. ``hydromodpy/solver/compatibility.py``

.. uml:: diagrams/process_extension_activity.wsd

See also
--------

- :doc:`../simulation/toml-to-solver-walkthrough` for the
  configuration-to-solver path that consumes process objects.
- :doc:`../solver/index` for the backend-side architecture.
- :doc:`../overview/test-families-and-quality-roles` for the test
  expectations on a new process / solver pair.

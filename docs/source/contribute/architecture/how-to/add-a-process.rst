Add a process
=============

A *process* is a runtime payload that one or more solver adapters consume.
Two ship today: ``flow`` (groundwater flow) and ``transport`` (particle tracking
and concentration). This page shows what a third one touches, using
``transport`` as the worked example. It is the process that was added after
``flow``, so every site it appears in is a site a new process needs.

Most additions are not a new process. A new solver for flow or transport is an
adapter bound to the existing pair: see :doc:`add-a-solver`. Add a process only
when the runtime payload is new, with its own initial conditions, boundary
conditions and sink or source vocabulary.

The base contract
-----------------

A process inherits ``ProcessSpatial[TInitialConditions]`` from
``hydromodpy/model/process_spatial.py``. The base keeps four containers
(``parameters``, ``initial_conditions``, ``boundary_conditions``,
``sinks_sources``) and asks the subclass for three methods:

.. code-block:: python

   class ProcessSpatial(ABC, Generic[TInitialConditions]):
       @abstractmethod
       def build_initial_conditions(self, initial_conditions) -> TInitialConditions | None: ...

       @abstractmethod
       def set_boundary_conditions(self, boundary_conditions: dict): ...

       @abstractmethod
       def set_sinks_sources(self, sinks_sources: dict): ...

Its configuration is a ``HydroModelBase`` that declares what the process reads.
Flow declares ``param``, ``ic``, ``bc`` and ``sinks_sources``. Transport declares one
block per solver. A process shares no base configuration, so a process never carries
a key it does not read.

Where a process lives
---------------------

``hydromodpy/model/transport/`` is the smallest complete example:

.. code-block:: text

   hydromodpy/model/transport/
   |-- __init__.py             a docstring only
   |-- transport.py            Transport(ProcessSpatial[TransportInitialConditions])
   `-- transport_config.py     TransportConfig(ProcessSpatialConfig) and one block per solver

``hydromodpy/model/`` holds the large one: ``model.py`` and ``flow_config.py``, with
``boundaries/`` (boundary condition registry and binders) and ``sinks_sources/``.
Read ``transport`` first.

Where a process is wired
------------------------

Search the tree for ``transport`` to find every site. These are the ones that
make it a process and not just a package:

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - File
     - What it does for the process
   * - ``model/<name>/<name>.py``
     - The runtime class, a subclass of ``ProcessSpatial``.
   * - ``model/<name>/<name>_config.py``
     - The Pydantic model, a subclass of ``ProcessSpatialConfig``, with one
       block per solver that serves the process.
   * - ``config/hydromodpy_config.py``
     - A field on ``HydroModPyConfig`` that makes ``[<name>]`` a TOML section
       (``transport`` is declared there), and its entry in the section loader
       table of the same file.
   * - ``solver/base/simulation_config.py``
     - A ``<Name>ProcessConfig`` with ``type: Literal["<name>"]`` and a list of
       ``solvers``, added to the ``SimulationProcessConfig`` union. This is what
       lets ``[[simulation.process]]`` declare ``type = "<name>"``. A simulation
       holds at most one process of each type.
   * - ``core/state/run_state.py``
     - A member of ``SetupContext`` that holds the built object
       (``setup.flow``, ``setup.transport``).
   * - ``solver/base/runner.py``
     - An ``ensure_<name>`` function that builds the object from the config, an
       entry in ``_COMPONENT_ENSURERS``, and the components the process needs in
       ``_REQUIRED_COMPONENTS_BY_PROCESS`` (``transport`` needs ``flow`` and
       ``transport``). A name is imported from the module that defines it, so
       nothing is exported from a package file.
   * - ``workflow/steps/setup.py``
     - The calls to ``ensure_flow`` and ``ensure_transport`` that build the
       objects once the configuration is resolved. Add yours next to them.
   * - ``solver/base/registry.py``
     - One entry per solver in ``_BUILTIN_PATHS``, ``_BUILTIN_EXTRACTOR_PATHS``
       and ``_BUILTIN_CAPABILITIES``, keyed ``("<name>", "<solver>")``. The
       process type becomes known to the planner as soon as one adapter is
       registered.
   * - ``calibration/runners/trial.py``
     - The trial copy of the setup context resets ``flow`` and ``transport`` to
       ``None`` so each trial builds its own. A new member needs the same line.
   * - ``_lazy.py``
     - The public exports of the runtime class and its config, if the
       class belongs to the public API.

Order of work
-------------

1. **Write the runtime class and its config** in ``model/<name>/``, in the
   shape of ``transport.py`` and ``transport_config.py``. Give every field a
   ``Profile``, a unit and a description: the parameter reference is generated
   from them (:doc:`add-a-config-field`).
2. **Declare the TOML section** on ``HydroModPyConfig`` and add the matching
   ``<Name>ProcessConfig`` to the ``SimulationProcessConfig`` union.
3. **Build the object** with an ``ensure_<name>`` function, register it in the
   runner tables, and call it from ``workflow/steps/setup.py``.
4. **Bind a solver.** The adapter declares ``process_type = "<name>"``, a
   ``solver_name`` and ``requires``, the earlier runs it depends on.
   ``Modflow6GwtTransportAdapter`` requires ``("flow", "modflow6")``, so the
   planner refuses a transport run that comes before its flow run. The adapter
   is the subject of :doc:`add-a-solver`; the planner reads ``requires`` in
   ``solver/base/planner.py``.
5. **Refuse impossible combinations** in the root validator of
   ``HydroModPyConfig``, in the way ``transport`` and the Boussinesq backend are
   checked together.

The workflow steps are process-agnostic. They hand the objects over through
``setup.flow`` and ``setup.transport`` of the run context, so a new process
needs no new pipeline step unless it needs its own data chain.

Tests to add
------------

- **Unit** under ``tests/unit/model/<name>/``, in the style of
  ``test_transport_process.py``: the config loads, a mapping builds the object,
  an unknown key is refused.
- **Unit** for the planner: a ``[[simulation.process]]`` entry of the new type
  expands into one run per solver and respects ``requires``.
- **Validation** with an analytical reference when the process carries
  non-trivial mathematics, so tolerances are explicit from the start
  (:doc:`add-a-test`).

Layer rules
-----------

- ``model`` imports ``core``, ``schema``, ``spatial`` and itself
  (``tests/unit/architecture/layer_matrix.yaml``). Solver code is in
  ``solver/<backend>/``, never in ``model/``.
- Initial conditions, boundary conditions and sinks and sources stay
  process-specific. The shared base in ``model/process_spatial.py`` and ``model/payloads.py`` is deliberately narrow.
- Run the architecture gate after the first import you add:
  ``python -m pytest tests/unit/architecture -q``.

See also
--------

- :doc:`../packages/model` for the model package map.
- :doc:`add-a-solver` for the adapter side.
- :doc:`add-a-config-field` for the configuration side.
- :doc:`../process/process-architecture` for the runtime handoff diagrams.

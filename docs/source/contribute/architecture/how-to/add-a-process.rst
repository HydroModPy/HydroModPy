Add a process
=============

A *process* is a kind of run of the plan of a simulation, with the solvers and
the options that serve it. Two ship today: ``flow`` (groundwater flow) and
``transport`` (particle tracking and concentration). This page shows what a
third one touches, using ``flow`` where a process carries a runtime payload and
``transport`` where it does not. It is the process that was added after
``flow``, so every site it appears in is a site a new process needs.

Most additions are not a new process. A new solver for ``flow`` or
``transport`` is an adapter bound to the pair that already exists: see
:doc:`add-a-solver`. Add a process only when the runs themselves are new,
with their own options and their own declared reads and requires.

The shape of a process
----------------------

A process holds a configuration, a process entry, and registered solvers. The
configuration is a ``HydroModelBase`` under ``model/<name>/<name>_config.py``
that declares what the process reads. Flow declares ``param``, ``ic``, ``bc``
and ``sinks_sources``. Transport declares one validated block per solver, and
each solver of the process has a table under the name the solver registry uses,
``[transport.modflow6]`` for instance, checked the way ``[solver.<name>]`` is.
A process shares no base configuration, so a process never carries a key it
does not read.

One process also carries a runtime payload, an object built once by the
pipeline and read by its adapters. ``flow`` does: the ``Flow`` of
``model/flow.py``. A process that does not, like ``transport``, needs nothing
built for it. Its adapters work from the arguments the runner passes,
``build(model, options, slot, upstream)``, where ``model`` is the frozen
``Model`` of the upstream run the process follows, ``options`` its own table,
and ``upstream[0]`` the ``SolverRun`` that produced what ``reads`` declares.
A transport works in the folder of that upstream run.

Where a process lives
---------------------

``hydromodpy/model/transport/`` is the smallest complete example:

.. code-block:: text

   hydromodpy/model/transport/
   |-- __init__.py             a docstring only
   `-- transport_config.py     TransportConfig and one parameter block per solver

The solvers of the process live with their backends:

.. code-block:: text

   hydromodpy/solver/<backend>/
   |-- adapter.py              the flow adapter, when the process runs on a flow run
   `-- <engine module>         one transport solver: its model and its adapter

The MT3DMS adapter, for instance, is in
``hydromodpy/solver/modflow_nwt/mt3dms/mt3dms.py``, beside the engine model it
drives, because a solver of a process is filed with the code it solves.
``hydromodpy/model/`` holds the large configuration case: ``flow_config.py``,
with ``boundaries/`` (boundary condition registry and binders) and
``sinks_sources/``. Read ``transport`` first.

Where a process is wired
------------------------

Search the tree for ``transport`` to find every site. These are the ones that
make it a process and not just a package:

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - File
     - What it does for the process
   * - ``model/<name>/<name>_config.py``
     - The Pydantic model, with one block per solver that serves the process,
       read through ``options_of(name)`` and ``named_tables`` at the registry
       name of each solver.
   * - ``config/hydromodpy_config.py``
     - A field on ``HydroModPyConfig`` that makes ``[<name>]`` a TOML section
       (``transport`` is declared there), and its entry in the section loader
       table of the same file.
   * - ``solver/base/simulation_config.py``
     - A ``<Name>ProcessConfig`` with ``kind: Literal["<name>"]`` and a list of
       ``solvers``, added to the ``SimulationProcessConfig`` union. This is what
       lets ``[[simulation.process]]`` declare ``kind = "<name>"``. A simulation
       holds at most one process of each type.
   * - ``solvers`` checks at read time
     - The registry refuses a ``solvers`` name that no adapter serves, with the
       names this installation serves.
   * - ``solver/base/registry.py``
     - One adapter and one extractor per solver in ``_BUILTIN_PATHS`` and
       ``_BUILTIN_EXTRACTOR_PATHS``, keyed ``"<process_type>_<name>"``. The
       adapter carries the twelve attributes of the port. The process type
       becomes known to the planner as soon as one adapter is registered.
   * - ``config/cross_checks.py``
     - The refusals derived from what the process declares: every name in
       ``reads`` must be written by the solver of the run before it, and the
       ``requires`` of each solver must hold one run of the plan. A trait of
       the model a backend leaves out is refused the same way.
   * - ``_lazy.py``
     - The public exports of the process, if it belongs to the public API.
   * - ``core/state/run_state.py`` (payload processes)
     - A member of ``SetupContext`` that holds the built object. ``flow``
       holds ``setup.flow`` and ``setup.model``, the frozen ``Model`` of the
       run that the ``prepare_solver`` step builds. A process that reads only
       options, its slot and its upstream runs adds no member.
   * - ``workflow/steps/`` (payload processes)
     - The step that builds the payload into ``SetupContext``, as ``setup``
       builds ``setup.flow``.

Order of work
-------------

1. **Write the configuration** in ``model/<name>/<name>_config.py``, in the
   shape of ``transport_config.py``. Give every field a ``Profile``, a unit and
   a description: the parameter reference is generated from them
   (:doc:`add-a-config-field`). A solver that needs no option of its own keeps
   none.
2. **Declare the TOML section** on ``HydroModPyConfig`` and add the matching
   ``<Name>ProcessConfig`` to the ``SimulationProcessConfig`` union.
3. **Bind a solver.** The adapter declares ``process_type = "<name>"``, a
   ``name``, ``reads`` and ``requires`` (and the other attributes of the port),
   and lives in the file of its engine under ``hydromodpy/solver/<backend>/``.
   ``Modflow6GwtTransportAdapter`` requires ``("flow", "modflow6")``, so the
   planner refuses a transport run that comes before its flow run. The adapter
   is the subject of :doc:`add-a-solver`; the planner reads ``requires`` in
   ``solver/base/planner.py``.
4. **Refuse impossible combinations** in ``config/cross_checks.py``, from what
   the backends declare, without naming a backend: a ``reads`` name the flow
   does not write, a ``requires`` the plan does not hold, a trait of the model
   left out of ``supports``.

A process that carries a payload adds to this list the runtime class, its
member on ``SetupContext``, the step that builds it and an adapter that reads
only that object and its arguments. The workflow steps are process-agnostic
beyond that, so a new process needs no new pipeline step unless it needs its
own data chain.

Tests to add
------------

- **Unit** under ``tests/unit/model/<name>/``, in the style of
  ``test_transport_config.py``: the config loads, a block is checked by the
  ``options`` class of a solver, an unknown key is refused.
- **Unit** for the planner: a ``[[simulation.process]]`` entry of the new type
  expands into one run per solver and respects ``requires``.
- **Contract** on the port, in ``tests/contract/test_solver_backend_contract.py``:
  the new solver answers the members a backend of its process type answers.
- **Scenario** in ``tests/scenarios/``: one chain of the process behind the
  run it reads, played by ``hmp run``. The transport chains of
  ``test_transport_chains.py`` are the worked example.
- **Validation** with an analytical reference when the process carries
  non-trivial mathematics, so tolerances are explicit from the start
  (:doc:`add-a-test`).

Layer rules
-----------

- ``model`` imports ``core``, ``schema``, ``catchment``, ``mesh`` and itself
  (``tests/unit/architecture/layer_matrix.yaml``). Solver code is in
  ``solver/<backend>/``, never in ``model/``, and the adapter of a solver is in
  the file of its engine.
- The shared base in ``model/process_spatial.py`` and ``model/payloads.py`` is
  deliberately narrow, and a process whose solvers read options plus upstream
  runs adds nothing to it.
- Run the architecture gate after the first import you add:
  ``python -m pytest tests/unit/architecture -q``.

See also
--------

- :doc:`../packages/model` for the model package map.
- :doc:`add-a-solver` for the adapter side.
- :doc:`add-a-config-field` for the configuration side.
- :doc:`../process/process-architecture` for the runtime handoff diagrams.

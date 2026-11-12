Add a process
=============

A *process* is a kind of run of the plan of a simulation, with the solvers and the options
that serve it. Two ship, ``flow`` and ``transport``. This page shows what a third one
touches, with ``flow`` as the process that carries a runtime payload and ``transport`` as
the one that does not.

Most additions are not a new process. A new solver for ``flow`` or ``transport`` is an
adapter, see :doc:`add-a-solver`. Add a process only when the runs themselves are new, with
their own options, ``reads`` and ``requires``.

The shape of a process
----------------------

A process holds a configuration, a process entry and registered solvers. The
configuration is a ``HydroModelBase`` under ``model/<name>/<name>_config.py`` that declares
what the process reads. Transport declares one validated block per solver, under the name
the solver registry uses, ``[transport.modflow6]`` for instance.

One process also carries a runtime payload, an object built once by the
pipeline and read by its adapters. ``flow`` does: the ``Flow`` of
``model/flow.py``. A process that does not, like ``transport``, needs nothing
built for it. Its adapters work from the arguments the runner passes,
``build(model, options, slot, upstream)``, where ``model`` is the frozen
``Model`` of the upstream run the process follows, ``options`` its own table,
and ``upstream[0]`` the ``SolverRun`` that produced what ``reads`` declares.
A transport works in the folder of that upstream run.

Files to create
---------------

``hydromodpy/model/transport/`` is the smallest complete example. It holds a docstring-only
``__init__.py`` and ``transport_config.py`` with ``TransportConfig`` and one parameter
block per solver. The solvers of the process live with their backends, in the file of the
engine they drive, as the MT3DMS adapter is in
``hydromodpy/solver/modflow_nwt/mt3dms/mt3dms.py``. ``hydromodpy/model/flow_config.py`` is
the large case. Read ``transport`` first.

Register
--------

Search the tree for ``transport`` to find every site. These make it a process and not
just a package:

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
       (``transport`` is declared there). Its row goes in ``SECTIONS`` of
       ``config/section_loader.py``.
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
       ``_BUILTIN_EXTRACTOR_PATHS``, keyed ``"<process_type>_<name>"``. A plugin publishes the groups of :doc:`plug-into-a-port` instead. The
       adapter carries the twelve attributes of the port. The process type
       becomes known to the planner as soon as one adapter is registered.
   * - ``config/solver_supports.py``
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

Write the configuration first, with a ``Profile``, a unit and a description on every field
(:doc:`add-a-config-field`). Declare the section on ``HydroModPyConfig`` and add the
``<Name>ProcessConfig`` to the union. Then bind a solver: the adapter declares
``process_type = "<name>"``, ``reads`` and ``requires``, as
``Modflow6GwtTransportAdapter`` requires ``("flow", "modflow6")``, so the planner refuses a
transport run that comes before its flow run (:doc:`add-a-solver`). Last, refuse impossible
combinations in ``config/solver_supports.py`` from what the backends declare, without
naming a backend. A process with a payload adds its runtime class, its member on
``SetupContext`` and the step that builds it.

Test
----

- **Unit** under ``tests/unit/model/<name>/``, in the style of
  ``test_transport_config.py``: the config loads, a block is checked by the
  ``options`` class of a solver, an unknown key is refused.
- **Unit** for the planner: a ``[[simulation.process]]`` entry of the new type
  expands into one run per solver and respects ``requires``.
- **Contract** on the port, in ``tests/ports/test_solver.py``:
  the new solver answers the members a backend of its process type answers.
- **Scenario** in ``tests/scenarios/``: one chain of the process behind the
  run it reads, played by ``hmp run``. The transport chains of
  ``test_transport_chains.py`` are the worked example.
- **Validation** with an analytical reference when the process carries
  non-trivial mathematics, so tolerances are explicit from the start
  (:doc:`add-a-test`).

Run ``python -m pytest tests/unit/architecture -q`` after the first import you add. The
imports the layer matrix allows are in :doc:`../generated/layers`. Solver code stays in
``solver/<backend>/``, never in ``model/``.

See also
--------

- :doc:`../packages/model` for the model package map.
- :doc:`add-a-solver` for the adapter side.
- :doc:`add-a-config-field` for the configuration side.
- :doc:`../engines/processes-and-boundaries` for the runtime handoff.

Process/Solver Registry
=======================

HydroModPy does not treat solvers as one flat backend list. Runtime execution
is keyed by a pair:

.. code-block:: text

   (process_type, solver_name)

The pair is resolved by ``hydromodpy.solver.base.registry``. The simulation
planner expands each declarative ``[[simulation.process]]`` entry into one
``ProcessRun`` per solver, validates upstream requirements, and then the runner
instantiates the matching adapter.

Why This Matters
----------------

The same word "solver" can mean different things depending on the process:

- ``modflow6`` under ``flow`` means a MODFLOW 6 GWF groundwater-flow solve.
- ``modflow6gwt`` under ``transport`` means a MODFLOW 6 GWT concentration
  transport solve.
- ``timeseries`` under ``postprocess`` is not a numerical PDE backend; it is
  an executable post-processing stage.

The process type therefore defines the contract. The solver name defines the
implementation selected for that contract.

Current Built-In Pairs
----------------------

.. list-table::
   :header-rows: 1
   :widths: 18 18 34 30

   * - Process
     - Solver
     - Adapter class
     - Dependency rule
   * - ``flow``
     - ``modflownwt``
     - ``ModflowNwtFlowAdapter``
     - None.
   * - ``flow``
     - ``modflow6``
     - ``Modflow6FlowAdapter``
     - None.
   * - ``flow``
     - ``boussinesq``
     - ``BoussinesqFlowAdapter``
     - None.
   * - ``transport``
     - ``modpath``
     - ``ModpathTransportAdapter``
     - Requires an earlier ``flow/modflownwt`` run.
   * - ``transport``
     - ``mt3dms``
     - ``Mt3dmsTransportAdapter``
     - Requires an earlier ``flow/modflownwt`` run.
   * - ``transport``
     - ``modflow6gwt``
     - ``Modflow6GwtTransportAdapter``
     - Requires an earlier ``flow/modflow6`` run.
   * - ``postprocess``
     - ``timeseries``
     - ``TimeseriesPostprocessAdapter``
     - Stub; planned extension point.
   * - ``postprocess``
     - ``netcdf``
     - ``NetcdfPostprocessAdapter``
     - Stub; planned extension point.
   * - ``display``
     - ``flow``
     - ``FlowDisplayAdapter``
     - Stub; planned extension point.
   * - ``display``
     - ``transport``
     - ``TransportDisplayAdapter``
     - Stub; planned extension point.

Execution Shape
---------------

One declarative process can expand into several concrete runs:

.. code-block:: toml

   [[simulation.process]]
   id = "transport_main"
   type = "transport"
   solvers = ["modpath", "mt3dms"]

The planner emits:

.. code-block:: text

   transport_main::modpath
   transport_main::mt3dms

Each concrete run stores:

- ``process_id``: the TOML process identifier, for example
  ``transport_main``.
- ``process_type``: the contract family, for example ``transport``.
- ``solver``: the selected implementation, for example ``mt3dms``.
- ``depends_on``: resolved upstream run ids required by the adapter.

Dependency Semantics
--------------------

Dependencies are declared by adapter classes through a ``requires`` attribute.
For example, a transport adapter can require a compatible flow run:

.. code-block:: python

   class Mt3dmsTransportAdapter:
       process_type = "transport"
       solver_name = "mt3dms"
       requires = (("flow", "modflownwt"),)

The planner is intentionally strict and backward-looking. It does not reorder
the plan. If ``transport/mt3dms`` appears before a matching
``flow/modflownwt`` run, planning fails with an explicit dependency error.

Output Extractors
-----------------

Adapter registration answers "how do we execute this process/solver pair?".
Extractor registration answers "how do we ingest raw outputs after execution?".

Output extractors are keyed by solver name, because the raw file format is
usually backend-specific:

.. list-table::
   :header-rows: 1
   :widths: 22 38 40

   * - Solver
     - Extractor role
     - Typical outputs
   * - ``modflownwt``
     - Flow output ingestion.
     - Heads, budgets, derived flow variables.
   * - ``modflow6``
     - Flow output ingestion.
     - MODFLOW 6 heads, budgets, mesh-aware outputs.
   * - ``boussinesq``
     - In-house flow output ingestion.
     - Boussinesq heads and exchange terms.
   * - ``modpath``
     - Particle output ingestion.
     - Pathlines and endpoints.
   * - ``mt3dms``
     - Concentration output ingestion.
     - Species concentration arrays and derived products.
   * - ``modflow6gwt``
     - MODFLOW 6 GWT concentration output ingestion.
     - Species concentration arrays and derived products.

Generalizing To New Processes
-----------------------------

Adding a new process should follow the same pattern:

1. Define the process contract and configuration model.
2. Decide whether the process is a physical PDE process, a forcing process, an
   analysis process, or a presentation process.
3. Add one adapter per supported solver or executor.
4. Register the adapter under ``(process_type, solver_name)``.
5. Declare ``requires`` if the new process consumes outputs from earlier
   process runs.
6. Add an output extractor if the solver writes raw files that must be
   ingested into the simulation catalog.
7. Add a row to the user-facing process map and scientific capability matrix.

Example future physical process:

.. code-block:: text

   process_type = "heat"
   solver_name = "modflow6gwe"
   requires = (("flow", "modflow6"),)

Example future analysis process:

.. code-block:: text

   process_type = "metrics"
   solver_name = "water_balance"
   requires = (("flow", "modflow6"),)

Code Reading Map
----------------

- ``hydromodpy.solver.base.registry``:
  canonical registry for adapters and extractors.
- ``hydromodpy.simulation.planning.config``:
  validates declarative ``[[simulation.process]]`` entries.
- ``hydromodpy.simulation.planning.planner``:
  expands process declarations into executable ``ProcessRun`` objects.
- ``hydromodpy.simulation.execution.runner``:
  executes runs and dispatches to registered adapters.
- ``hydromodpy.solver.<backend>.adapters``:
  concrete process/solver adapters.

Related Pages
-------------

- :doc:`../../user_guide/solver-process-map`
- :doc:`flow/index`
- :doc:`transport/index`
- :doc:`workflow-stages/index`
- :doc:`../../scientific/solvers/flow/index`
- :doc:`../../scientific/solvers/transport/index`
- :doc:`../process/index`
- :doc:`index`

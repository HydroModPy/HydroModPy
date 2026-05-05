Solvers By Process
==================

HydroModPy should be read as a process-first modelling stack:

1. choose the physical or operational process to execute,
2. choose one or more solvers for that process,
3. let the planner expand the request into concrete ``process/solver`` runs.

This is more explicit than a flat list of backends. ``modflow6`` is a flow
solver when used as ``flow/modflow6``. ``modflow6gwt`` is a transport solver
when used as ``transport/modflow6gwt``. ``timeseries`` and ``netcdf`` are not
groundwater equations; they are planned post-processing stages.

Current Process Families
------------------------

.. list-table::
   :header-rows: 1
   :widths: 18 28 28 26

   * - Process type
     - Role
     - Current solver names
     - Status
   * - ``flow``
     - Groundwater-flow simulation. Produces heads, storage changes, boundary
       exchanges, and flow-budget outputs.
     - ``modflownwt``, ``modflow6``, ``boussinesq``
     - Active numerical process.
   * - ``transport``
     - Particle tracking or concentration transport driven by a previous flow
       run.
     - ``modpath``, ``mt3dms``, ``modflow6gwt``
     - Active numerical process, with explicit upstream flow requirements.
   * - ``postprocess``
     - Derive secondary products after a simulation run.
     - ``timeseries``, ``netcdf``
     - Registry stubs today; intended extension point.
   * - ``display``
     - Generate presentation outputs from stored results.
     - ``flow``, ``transport``
     - Registry stubs today; intended extension point.

Flow Solvers
------------

Use a ``flow`` process when the main question is hydraulic head, groundwater
exchange, storage, recharge response, or stream/ocean/drainage boundary
behaviour.

.. list-table::
   :header-rows: 1
   :widths: 18 24 24 34

   * - Solver
     - Best fit
     - Typical support
     - Notes
   * - ``modflownwt``
     - Legacy MODFLOW-family groundwater flow.
     - Structured ``sgrid`` supports.
     - Important for continuity with historical studies and for the
       ``MODPATH`` / ``MT3DMS`` ecosystem.
   * - ``modflow6``
     - Modern MODFLOW-family groundwater flow.
     - Structured grids and runtime DISV-style unstructured meshes.
     - Preferred route when irregular meshes, modern package semantics, or
       MODFLOW 6 GWT compatibility matter.
   * - ``boussinesq``
     - In-house shallow-groundwater flow.
     - Triangular runtime meshes.
     - Useful for simulation comparisons and explicit Boussinesq-style
       formulations; still under active validation.

Minimal flow plan:

.. code-block:: toml

   [simulation.time]
   start_datetime = "2000-01-01"
   end_datetime = "2000-12-31"
   step_value = "1 month"

   [[simulation.process]]
   id = "flow_main"
   type = "flow"
   solvers = ["modflow6"]

Transport Solvers
-----------------

Use a ``transport`` process when the question depends on a previously computed
flow field: travel time, particle paths, concentration advection, dispersion,
or decay.

.. list-table::
   :header-rows: 1
   :widths: 18 24 22 36

   * - Solver
     - Transport type
     - Requires
     - Notes
   * - ``modpath``
     - Particle tracking.
     - Earlier ``flow/modflownwt`` run.
     - Uses the MODFLOW-NWT flow model as its velocity source.
   * - ``mt3dms``
     - Concentration transport.
     - Earlier ``flow/modflownwt`` run.
     - Uses MT3DMS-style species, dispersivity, diffusion, and decay
       parameters.
   * - ``modflow6gwt``
     - Concentration transport.
     - Earlier ``flow/modflow6`` run.
     - MODFLOW 6 GWT route aligned with a MODFLOW 6 GWF flow model.

MODFLOW-NWT flow followed by MODPATH and MT3DMS:

.. code-block:: toml

   [[simulation.process]]
   id = "flow_main"
   type = "flow"
   solvers = ["modflownwt"]

   [[simulation.process]]
   id = "transport_main"
   type = "transport"
   solvers = ["modpath", "mt3dms"]

MODFLOW 6 flow followed by MODFLOW 6 GWT:

.. code-block:: toml

   [[simulation.process]]
   id = "flow_main"
   type = "flow"
   solvers = ["modflow6"]

   [[simulation.process]]
   id = "transport_main"
   type = "transport"
   solvers = ["modflow6gwt"]

The planner does not reorder processes. Declare the upstream ``flow`` process
before the downstream ``transport`` process so dependency resolution can bind
the transport adapter to the correct flow model.

Solver-Specific Transport Parameters
------------------------------------

Transport parameters live under ``[transport.<solver>.parameters]``. This
keeps process-wide orchestration separate from solver-specific numerical
options.

.. code-block:: toml

   [transport.modpath.parameters]
   zone_partic = "domain"
   track_dir = "forward"
   cell_div = 2

   [transport.mt3dms.parameters]
   spc_name = "NO3"
   sconc_init = 0.0
   sconc_input = 30.0
   disp_long = 10.0
   rate_decay = 0.0

   [transport.modflow6gwt.parameters]
   spc_name = "NO3"
   sconc_init = 0.0
   sconc_input = 30.0
   disp_long = 10.0

Generalized Categories
----------------------

The same structure can cover future processes without changing the mental
model:

.. list-table::
   :header-rows: 1
   :widths: 18 30 28 24

   * - Category
     - Example process types
     - Example solvers or adapters
     - Expected dependency style
   * - Physical PDE processes
     - ``flow``, ``transport``, future ``heat`` or ``reactive_transport``
     - Numerical engines.
     - Often depend on mesh, domain, forcing, and sometimes earlier process
       outputs.
   * - Hydrological or forcing processes
     - Future ``recharge`` or ``surface_runoff``
     - Forcing builders or hydrological models.
     - Usually feed ``flow`` rather than consume flow outputs.
   * - Analysis processes
     - ``postprocess``, future ``metrics`` or ``uncertainty``
     - Catalog readers, metric builders, exporters.
     - Usually depend on completed simulation outputs.
   * - Presentation processes
     - ``display``, future ``report``
     - Figure and report generators.
     - Usually depend on catalog data and derived analysis outputs.

Practical Selection Rules
-------------------------

- Start from the question, not from the backend name.
- Use ``flow`` when the output of interest is the water table or flow budget.
- Add ``transport`` only when the transport result needs a previously solved
  flow model.
- Keep each process block focused: process type declares the modelling task;
  solver name declares the implementation.
- Prefer the scientific capability matrix when comparing assumptions, mesh
  support, and validation status.

Related Pages
-------------

- :doc:`../theory/solvers/flow/index`
- :doc:`../theory/solvers/flow/modflow/index`
- :doc:`workflows/index`
- :doc:`../theory/solvers/solver-capability-matrix`
- :doc:`../theory/solvers/index`
- :doc:`../architecture/solver/index`
- :doc:`../architecture/process/index`

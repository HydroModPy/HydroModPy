Solvers
=======

.. note::

   Use this page when the question is:
   "Which process do I need, which backend implements it, and which numerical
   option matters before I trust the result?"

HydroModPy is a process-first modelling stack. Pick the physical or
operational process to execute, pick one or more solvers for that process,
and let the planner expand the request into concrete ``process/solver``
runs. The same backend can play different roles depending on context:
``modflow6`` is a flow solver when used as ``flow/modflow6``,
``modflow6gwt`` is a transport solver when used as
``transport/modflow6gwt``.

Pick a flow solver
------------------

HydroModPy currently exposes three flow solvers. They are not
interchangeable: each one constrains the mesh family, the available
packages, and the calibration budget.

.. list-table::
   :header-rows: 1
   :widths: 18 22 22 38

   * - Solver
     - Best fit
     - Mesh support
     - Notes
   * - ``modflownwt``
     - Legacy MODFLOW-family flow
     - Structured ``sgrid`` only
     - Continuity with historical studies; gateway to the ``MODPATH`` and
       ``MT3DMS`` ecosystem.
   * - ``modflow6``
     - Modern MODFLOW-family flow
     - Structured ``sgrid`` and runtime DISV-style irregular meshes
     - Preferred when irregular meshes, modern package semantics, or
       MODFLOW 6 GWT transport coupling matter.
   * - ``boussinesq``
     - In-house shallow-groundwater flow
     - Triangular runtime meshes from the Gmsh pipeline
     - Useful for solver-to-solver comparisons and explicit Boussinesq
       formulations; still under active validation.

The active backend is declared in ``[solver]``. Backend-specific options
live under ``[modflow6]`` or ``[modflownwt]``. Process binding remains in
``[[simulation.process]]``.

.. code-block:: toml

   [solver]
   solver_engine = "modflow6"

   [modflow6.runtime]
   xt3d = true

   [[simulation.process]]
   id = "flow_main"
   type = "flow"
   solvers = ["modflow6"]

Process families
----------------

The planner reads each ``[[simulation.process]]`` block, binds it to one
or more solvers, and orders dependent processes (transport after flow).
Four process families exist today.

.. list-table::
   :header-rows: 1
   :widths: 18 28 28 26

   * - Process type
     - Role
     - Current solver names
     - Status
   * - ``flow``
     - Groundwater-flow simulation. Produces heads, storage changes,
       boundary exchanges, and flow-budget outputs.
     - ``modflownwt``, ``modflow6``, ``boussinesq``
     - Active numerical process.
   * - ``transport``
     - Particle tracking or concentration transport driven by a previous
       flow run.
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

Transport solvers
-----------------

Use a ``transport`` process when the question depends on a previously
computed flow field: travel time, particle paths, concentration advection,
dispersion, or decay.

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

The planner does not reorder processes. Declare the upstream ``flow``
process before the downstream ``transport`` process so dependency
resolution can bind the transport adapter to the correct flow model.

.. tab-set::

   .. tab-item:: MODFLOW-NWT + MODPATH/MT3DMS

      .. code-block:: toml

         [[simulation.process]]
         id = "flow_main"
         type = "flow"
         solvers = ["modflownwt"]

         [[simulation.process]]
         id = "transport_main"
         type = "transport"
         solvers = ["modpath", "mt3dms"]

   .. tab-item:: MODFLOW 6 + GWT

      .. code-block:: toml

         [[simulation.process]]
         id = "flow_main"
         type = "flow"
         solvers = ["modflow6"]

         [[simulation.process]]
         id = "transport_main"
         type = "transport"
         solvers = ["modflow6gwt"]

Solver-specific transport parameters
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

Generalized categories
----------------------

The same structure can cover future processes without changing the mental
model.

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

Practical selection rules
-------------------------

- Start from the question, not from the backend name.
- Use ``flow`` when the output of interest is the water table or flow
  budget.
- Add ``transport`` only when the transport result needs a previously
  solved flow model.
- Keep each process block focused: process type declares the modelling
  task; solver name declares the implementation.
- Prefer the scientific capability matrix when comparing assumptions,
  mesh support, and validation status.

Decision matrix
---------------

.. list-table::
   :header-rows: 1
   :widths: 38 62

   * - Question
     - Best entry point
   * - What can each solver family represent?
     - :doc:`../theory/solvers/solver-capability-matrix`
   * - How do MODFLOW 6 and MODFLOW-NWT differ scientifically?
     - :doc:`../theory/solvers/modflow6-vs-modflownwt-scientific-comparison`
   * - Why is XT3D important on irregular meshes?
     - :doc:`../theory/solvers/xt3d-on-irregular-disv-meshes`
   * - Where are the analytical and semi-analytical validation cases?
     - :doc:`../capability_gallery/validation`
   * - Where are stable solver-to-solver comparison cases?
     - :doc:`../capability_gallery/simulation_comparison`
   * - Where is the solver package architecture documented?
     - :doc:`../architecture/solver/index`

Read more
---------

.. grid:: 1 2 2 2
   :gutter: 2

   .. grid-item-card:: Theory
      :link: ../theory/solvers/index
      :link-type: doc

      Solver families, governing equations, package semantics, and
      cross-cutting numerical notes.

   .. grid-item-card:: Validation
      :link: ../capability_gallery/validation
      :link-type: doc

      Analytical and semi-analytical comparisons rendered as reproducible
      teaching figures.

   .. grid-item-card:: Comparison
      :link: workflows/comparison
      :link-type: doc

      Shared-case studies that quantify solver, mesh, or option
      differences.

   .. grid-item-card:: Architecture
      :link: ../architecture/solver/index
      :link-type: doc

      Package boundaries, adapter contracts, and runtime handoff.

See also
--------

- :doc:`workflows/index` for the workflow-family map.
- :doc:`../theory/solvers/flow/index` and
  :doc:`../theory/solvers/flow/modflow/index` for solver-family theory.
- :doc:`../architecture/process/index` for the process planner.
- :doc:`../api/index` for the solver-facing API reference.

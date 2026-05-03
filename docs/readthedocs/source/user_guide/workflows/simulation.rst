Simulation Workflow
===================

``workflow = "simulation"`` runs one forward model. It turns one validated
configuration into one persisted run with solver outputs, catalog rows, result
stores, and optional figures.

Use it when the question is:
"Given this physical setup, what does one model run produce?"

Functional Role
---------------

The simulation workflow is the canonical HydroModPy forward run. It usually
performs these phases:

.. code-block:: text

   resolve workspace
       -> build geographic context
       -> load requested data
       -> build supports and mesh input
       -> build process plan
       -> run solver backend(s)
       -> ingest outputs
       -> render figures
       -> finalize catalog and result store

It is appropriate for:

- one MODFLOW-NWT, MODFLOW 6, or Boussinesq run;
- steady or transient flow simulations;
- solver-specific option testing;
- producing persisted results for later inspection or comparison.

It is not the right first choice when the watershed geometry is still
uncertain. Run ``overview`` first in that case.

Typical Command
---------------

.. code-block:: bash

   hmp run examples/projects/06_vire_selune/run_vire_mf6_irregular.toml

Reference examples:

- ``examples/projects/00_getting_started/project.toml``
- ``examples/projects/02_nancon_watershed/run_transient_nwt.toml``
- ``examples/projects/06_vire_selune/run_vire_mf6_irregular.toml``
- ``examples/projects/06_vire_selune/run_vire_nwt.toml``
- ``examples/projects/09_comparison_workflow/base_dupuit_shared_mesh.toml``

Representative Results
----------------------

.. figure:: /_static/capability_gallery/simulation/modflow6_gmsh_support_overview.png
   :alt: Support overview figure for a simulation workflow
   :width: 100%

   A simulation page should expose the support that the solver actually used,
   not only the input TOML that asked for it.

.. figure:: /_static/capability_gallery/simulation/modflow6_gmsh_flow_state_triptych.png
   :alt: Flow-state triptych for a simulation workflow
   :width: 100%

   The triptych is the main state diagnostic for one forward run: it keeps the
   spatial response readable before moving to budgets or downstream analytics.

.. figure:: /_static/capability_gallery/simulation/modflow6_gmsh_recharge_discharge_cumulative.png
   :alt: Cumulative recharge and discharge figure for a simulation workflow
   :width: 100%

   The cumulative curve is the fastest way to sanity-check the forcing
   chronology against the integrated hydraulic response.

Minimal Shape
-------------

.. code-block:: toml

   workflow = "simulation"

   [workspace]
   project_root = "outputs/my_run"

   [simulation]
   name = "my_first_forward_run"

   [simulation.time]
   start_datetime = "2020-01-01 00:00:00"
   end_datetime = "2020-12-31 00:00:00"
   step_value = "1 month"

   [[simulation.process]]
   id = "flow_main"
   type = "flow"
   solvers = ["modflow6"]

   [solver]
   solver_engine = "modflow6"

Important Parameters
--------------------

.. list-table::
   :header-rows: 1
   :widths: 28 32 40

   * - Section / field
     - Role
     - Practical guidance
   * - ``base_config``
     - Inherits a shared project TOML.
     - Use overlays for run-specific solver, time, or outlet changes.
   * - ``workflow``
     - Selects the forward-run launcher.
     - Must be ``"simulation"``.
   * - ``[simulation].name``
     - Human-readable run name in the catalog.
     - Use a short name that encodes basin, solver, and scenario.
   * - ``[simulation].run_id``
     - Optional stable output identifier.
     - Leave empty for filename-derived IDs unless you need strict output
       naming.
   * - ``[simulation].on_collision``
     - Controls what happens when a run name already exists.
     - ``replace`` is convenient for iteration; ``fail`` is safer for
       reproducible campaigns.
   * - ``[simulation.time]``
     - Defines stress-period and forcing alignment.
     - Check start/end dates and ``step_value`` before interpreting transient
       results.
   * - ``[[simulation.process]]``
     - Declares process type and active solvers.
     - For flow-only runs, use one process with ``type = "flow"``.
   * - ``[flow]``
     - Declares flow process parameters and boundary conditions.
     - This is where physical assumptions become runtime parameters.
   * - ``[mesh_catchment]``
     - Optional runtime catchment mesh used by solver backends.
     - Include it when MODFLOW 6 or Boussinesq should consume an irregular
       mesh.
   * - Backend sections
     - Tune solver-specific behavior.
     - Use ``[modflow6.*]`` or ``[modflownwt.*]`` only for backend-specific
       details.

Time Window Example
-------------------

.. code-block:: toml

   [simulation.time]
   start_datetime = "2000-01-01"
   end_datetime = "2002-12-31"
   step_value = "1 month"
   coverage_policy = "warn"

``coverage_policy = "warn"`` is useful while preparing data because it surfaces
forcing gaps without immediately blocking exploratory runs. Use ``"error"``
for production runs when forcing coverage must be complete.

Process Example
---------------

.. code-block:: toml

   [[simulation.process]]
   id = "flow_main"
   type = "flow"
   solvers = ["modflow6"]

The process declaration says what HydroModPy is asked to solve. The backend
sections say how a given solver family should solve it.

Outputs To Inspect
------------------

After a successful run, inspect in this order:

1. the catalog entry and run metadata;
2. solver logs and convergence messages;
3. support or mesh overview figure;
4. water-table maps and time-series outputs;
5. budget or recharge/discharge figures;
6. persisted Zarr or exported result tables if downstream analysis needs them.

Next Pages
----------

- :doc:`../../getting_started/simulation-walkthrough`
- :doc:`../../architecture/simulation/toml-to-solver-walkthrough`
- :doc:`../../scientific/foundations/groundwater-flow-problem-definition`
- :doc:`../../scientific/solvers/index`

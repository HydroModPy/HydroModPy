Worked MODFLOW Case: Nancon Transient NWT With ETP To EVT
=========================================================

Purpose
-------

This page is the first real-basin MODFLOW-NWT worked case in the scientific
documentation.

Its role is narrower than a full basin tutorial:

- show one public HydroModPy TOML that activates ``MODFLOW-NWT``,
- explain how ``data.etp`` becomes a runtime ``ETP`` forcing,
- show how HydroModPy feeds both ``RCH`` and ``EVT`` on the same run,
- and state clearly which figures and outputs should be inspected after
  execution.

Why This Case
-------------

The case is based on the public example project
``examples/projects/02_nancon_watershed``.

It is worth documenting because it exercises a part of the public MODFLOW-NWT
contract that is more specific than the analytical benchmarks:

- real watershed geometry,
- real climate-like forcing inputs,
- transient monthly periods,
- ``recharge`` and explicit ``etp`` both active,
- top drainage through ``DRN``,
- structured ``DIS`` plus legacy ``NWT`` / ``UPW`` / ``EVT`` assembly.

This makes it the clearest current worked case for the question:

   "On a real HydroModPy basin, how does ``ETP`` actually reach
   ``ModflowEvt(...)``?"

Files Used
----------

- Base project:
  ``examples/projects/02_nancon_watershed/project.toml``
- Run overlay:
  ``examples/projects/02_nancon_watershed/run_transient_nwt.toml``
- Example notes:
  ``examples/projects/02_nancon_watershed/README.md``
- Basin context figures:
  :doc:`../../capability_gallery/cases/geographic_nancon_identity_card`

Basin Context Already Documented
--------------------------------

The exact solver-result figures for this run are not yet committed into the
capability gallery, but the basin context and forcing context already are.

.. figure:: /_static/capability_gallery/geographic/geographic_nancon_identity_card_map_dem.png
   :alt: Nancon basin DEM context
   :width: 100%

   DEM context for the Nancon watershed used by the public project.

.. figure:: /_static/capability_gallery/geographic/geographic_nancon_identity_card_map_hydrography.png
   :alt: Nancon hydrography context
   :width: 100%

   Hydrographic context on the same basin support.

.. figure:: /_static/capability_gallery/geographic/geographic_nancon_identity_card_climatic_summary.png
   :alt: Nancon climatic summary
   :width: 100%

   Climatic summary for the same observed basin. This is not a solver result,
   but it gives the forcing context that later feeds recharge and ETP.

Minimal TOML Reading
--------------------

The run is split between a shared project TOML and a lighter overlay.

Shared project blocks
^^^^^^^^^^^^^^^^^^^^^

.. code-block:: toml

   [data]
   types = ["dem", "geology", "hydrography", "hydrometry", "recharge", "runoff", "etp"]

   [data.etp]
   date_start = "2000-01-01"
   date_end = "2002-12-31"

   [[data.etp.sources]]
   source = "custom"
   path = "etp_sim2_5347fa22_20000101_20251231.nc"

   [flow]
   active_sinks_sources = ["recharge", "etp"]
   active_bc = ["drainage"]
   flow_regime = "transient"

   [flow.bc.cauchy.drainage]
   id = "drainage"
   type = "cauchy"
   application_domain = "top"
   value = 0.0

This says:

- ETP is a loaded data family,
- the flow process explicitly activates both ``recharge`` and ``etp``,
- top drainage is active,
- the run is transient.

Run overlay
^^^^^^^^^^^

.. code-block:: toml

   base_config = "project.toml"
   workflow = "simulation"

   [simulation]
   name = "nancon_transient_nwt"

   [simulation.time]
   start_datetime = "2000-01-01"
   end_datetime = "2002-12-31"
   step_value = "1 month"

   [[simulation.process]]
   id = "flow_main"
   type = "flow"
   solvers = ["modflownwt"]

The overlay keeps the run definition short:

- one monthly transient window over three years,
- one flow process,
- solved by ``modflownwt``.

One Important Runtime Detail
----------------------------

The public TOML a user reads is not yet the exact solver payload.

HydroModPy first builds a process-level ``Flow`` object, then injects the
loaded recharge and ETP data into typed runtime structures:

- ``apply_recharge_load_result_to_flow(...)`` in
  ``hydromodpy/physics/flow/structure_binders.py``
- ``apply_etp_load_result_to_flow(...)`` in the same module
- ``Flow.set_recharge(...)`` and ``Flow.set_etp(...)`` in
  ``hydromodpy/physics/flow/flow.py``

That means the visible TOML intent:

- ``[data.etp]`` declares the source,
- ``flow.active_sinks_sources = ["recharge", "etp"]`` activates the category,

and the runtime object then carries:

- ``flow.sinks_sources["recharge"]`` as one typed ``FlowRechargeConfig``,
- ``flow.sinks_sources["etp"]`` as one typed ``FlowEtpConfig``.

This distinction matters because the MODFLOW-NWT adapter only reads the
runtime ``Flow`` object, not the raw TOML directly.

How HydroModPy Builds RCH And EVT On This Case
----------------------------------------------

The NWT adapter path is concentrated in
``hydromodpy/solver/modflow_nwt/modflow/flow_to_modflow_adapter.py``.

The sequence is:

1. ``_build_recharge_payload()``
   reads ``flow.sinks_sources["recharge"]``, converts units to SI ``m/s``,
   applies the ``first_clim`` policy, and prepares the ``RCH`` payload.
2. ``_build_etp_payload()``
   reads ``flow.sinks_sources["etp"]``, clips ETP to non-negative values, and
   prepares the ``EVT`` rate payload.
3. ``_merge_evt_payloads(...)``
   sums the EVT contribution from explicit ETP with any fallback EVT
   contribution coming from negative recharge.
4. ``build()``
   returns one ``FlowModflowInputs`` object containing:

   - ``rch_data``
   - ``evt_spd``
   - ``evt_surface_offset``
   - ``evt_extinction_depth``

5. ``Modflow.pre_processing(...)`` in
   ``hydromodpy/solver/modflow_nwt/modflow/nwt_solver.py`` converts those SI
   rates to solver time units and assembles:

   - ``flopy.modflow.ModflowRch(self.mf, rech=rch_data_solver)``
   - ``flopy.modflow.ModflowEvt(...)`` when ``evt_spd_solver`` is not ``None``

The exact ``EVT`` call is scientifically important. HydroModPy currently uses:

- ``evtr = evt_spd_solver``
- ``surf = self.top_elevation - surf_offset``
- ``exdp = evt_extinction_depth``
- ``nevtop = modflownwt.runtime.evt_nevtop``
- ``ievt = modflownwt.runtime.evt_ievt``
- ``ipakcb = modflownwt.runtime.evt_ipakcb``

So the public project choice is:

- one explicit ETP rate forcing,
- one extraction surface below topography,
- one extinction depth,
- one compact set of NWT EVT controls.

Why These Choices Are Reasonable
--------------------------------

For this real-basin public path, HydroModPy keeps the EVT contract compact on
purpose.

- ``active_sinks_sources = ["recharge", "etp"]`` makes the forcing split
  explicit at process level.
- ``ETP`` is handled as a dedicated outflow forcing, rather than hiding it
  inside a negative recharge series.
- ``surf = top - surface_offset`` keeps the land-surface interpretation easy to
  explain.
- ``exdp`` is exposed as one depth parameter instead of opening the whole
  legacy EVT option surface.
- ``DRN`` remains the top drainage package, so the run separates two ideas:

  - atmospheric extraction through ``EVT``,
  - head-dependent seepage release through ``DRN``.

Package Assembly On This Case
-----------------------------

For the documented Nancon NWT run, the public package reading is:

- ``DIS``:
  structured space/time support with monthly stress periods
- ``BAS``:
  startup heads and active-cell mask
- ``NWT``:
  nonlinear solve for the transient unconfined run
- ``UPW``:
  ``K``, ``Sy``, ``Ss``, and vertical conductivity control
- ``RCH``:
  diffuse recharge
- ``EVT``:
  dedicated ETP forcing
- ``DRN``:
  top drainage / seepage release
- ``OC``:
  systematic head and budget outputs

What this case does not primarily document:

- irregular MF6 ``DISV``,
- XT3D,
- ``CHD`` stage-style boundaries,
- wells,
- particle tracking or transport.

What To Inspect After Running It
--------------------------------

The project TOML already declares a useful default figure suite:

- ``piezometric_map``
- ``water_budget``
- ``hydrograph``
- ``recharge_map``
- ``seepage_map``

After:

.. code-block:: powershell

   hmp run examples/projects/02_nancon_watershed/run_transient_nwt.toml

the first outputs to inspect are:

- ``figures/nancon_transient_nwt/piezometric_map.*``
- ``figures/nancon_transient_nwt/water_budget.*``
- ``figures/nancon_transient_nwt/hydrograph.*``
- ``figures/nancon_transient_nwt/recharge_map.*``
- ``figures/nancon_transient_nwt/seepage_map.*``

Read them in that order:

1. ``piezometric_map`` for the groundwater state,
2. ``water_budget`` for mass-balance coherence,
3. ``hydrograph`` for the outlet response,
4. ``recharge_map`` for forcing context,
5. ``seepage_map`` for the drainage response on the basin support.

Why This Page Still Matters Without Committed Solver Figures
------------------------------------------------------------

The analytical worked cases are better for exact validation metrics.

This page answers a different need:

- how a public HydroModPy basin example is really wired,
- how ``data.etp`` reaches ``ModflowEvt(...)``,
- how ``RCH`` and ``EVT`` coexist in the NWT branch,
- and which outputs a contributor should inspect first after a real run.

In other words, it is a workflow-reading page more than a benchmark page.

Recommended Reading Order
-------------------------

1. :doc:`../../capability_gallery/cases/geographic_nancon_identity_card`
2. :doc:`../hydrology/forcing-time-aggregation-and-first-clim`
3. :doc:`modflow-package-semantics-and-boundary-conditions`
4. this Nancon NWT worked case
5. :doc:`modflow6-vs-modflownwt-scientific-comparison`

Current Limitation
------------------

The missing piece for this exact case is clear:

- the solver-result figures for ``nancon_transient_nwt`` are not yet published
  as committed capability-gallery assets.

So this page currently gives:

- the basin context,
- the exact package path,
- the runtime interpretation,
- the expected output files,

but not yet one versioned RTD gallery page for the final solver figures.

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
- Committed basin-result page:
  :doc:`../../capability_gallery/cases/nancon_transient_nwt`

Basin Context And Committed Result Page
---------------------------------------

The basin context and one stable basin-result page are now both committed in
the documentation:

- basin and forcing context through
  :doc:`../../capability_gallery/cases/geographic_nancon_identity_card`
- stable post-run diagnostics through
  :doc:`../../capability_gallery/cases/nancon_transient_nwt`

This scientific page still keeps the focus on the package path and option
rationale, not on repeating the gallery reading order.

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

Committed Simulation Results
----------------------------

The stable gallery case publishes the most useful result figures for this run.
They are repeated here because this page explains the package path that
produced them.

.. figure:: /_static/capability_gallery/simulation/nancon_transient_nwt_piezometric_map.png
   :alt: Piezometric map for the Nancon transient NWT run
   :width: 100%

   The piezometric map is the direct spatial expression of the solved head
   field after the NWT package assembly has run.

.. figure:: /_static/capability_gallery/simulation/nancon_transient_nwt_water_budget.png
   :alt: Water budget for the Nancon transient NWT run
   :width: 100%

   The budget is where the ``RCH``, ``EVT``, storage, and ``DRN`` choices become
   visible as integrated flow components.

.. figure:: /_static/capability_gallery/simulation/nancon_transient_nwt_hydrograph.png
   :alt: Observed and simulated hydrograph for the Nancon transient NWT run
   :width: 100%

   The hydrograph shows whether the package assembly produces a coherent
   outlet-scale response over the monthly transient window.

.. figure:: /_static/capability_gallery/simulation/nancon_transient_nwt_simulated_active_network_reference_overlay.png
   :alt: Simulated active network compared with observed hydrography on Nancon
   :width: 100%

   The active-network overlay should be read after the budget and hydrograph:
   it is a downstream spatial diagnostic of the drainage response.

How To Make EVT Matter In The Docs
----------------------------------

If the goal is to document the **effect** of activating ``EVT``, this single
worked case is not enough by itself.

The right documentation object is a small sensitivity family built on the same
Nancon basin:

.. figure:: /_static/theory/modflow/evt_sensitivity_reading_order.svg
   :alt: Recommended reading order for a Nancon EVT sensitivity comparison
   :width: 100%

   The comparison should first isolate the hydrological mechanism: ET and DRN
   budgets, outlet hydrograph, and water-table depth. Spatial overlays are
   useful only after those primary diagnostics explain what changed.

1. one run without explicit ``etp`` activation,
2. one baseline run with ``active_sinks_sources = ["recharge", "etp"]``,
3. one or two additional runs changing ``surface_offset`` and
   ``extinction_depth``.

In other words, the first contrast should be:

- **No EVT**:
  ``flow.active_sinks_sources = ["recharge"]``
- **Baseline EVT**:
  ``flow.active_sinks_sources = ["recharge", "etp"]``

Only after that should the docs add one second layer such as:

.. code-block:: toml

   [flow.sinks_sources.etp]
   surface_offset = 0.5
   extinction_depth = 0.5

versus:

.. code-block:: toml

   [flow.sinks_sources.etp]
   surface_offset = 2.0
   extinction_depth = 3.0

The outputs that should carry that comparison are, in order:

1. ``run.budget(component="et")`` and ``run.budget(component="drains")``
2. ``run.timeseries("discharge", station="_catchment")``
3. ``run.catchment_mean("watertable_depth")``
4. timestep maps of ``watertable_depth``, ``outflow_drain``, and ``seepage_areas``
5. only then the hydrographic overlay figures and active-network metrics

That ordering is important. If the comparison starts directly with one map
overlay, the documentation will hide the real hydrological question, which is
first the partition between:

- atmospheric extraction through ``EVT``,
- head-dependent release through ``DRN``,
- and the resulting outlet discharge response.

Why This Page Still Matters Beyond The Committed Gallery Page
-------------------------------------------------------------

The analytical worked cases are better for exact validation metrics.

This page answers a different need:

- how a public HydroModPy basin example is really wired,
- how ``data.etp`` reaches ``ModflowEvt(...)``,
- how ``RCH`` and ``EVT`` coexist in the NWT branch,
- and which outputs a contributor should inspect first after a real run.

In other words, it is a workflow-reading page more than a gallery-reading
page.

Recommended Reading Order
-------------------------

1. :doc:`../../capability_gallery/cases/geographic_nancon_identity_card`
2. :doc:`../hydrology/forcing-time-aggregation-and-first-clim`
3. :doc:`modflow-package-semantics-and-boundary-conditions`
4. this Nancon NWT worked case
5. :doc:`modflow6-vs-modflownwt-scientific-comparison`

Current Scope Boundary
----------------------

The committed gallery page for this exact run now exists:

- :doc:`../../capability_gallery/cases/nancon_transient_nwt`

So the split is now deliberate:

- this scientific page gives the basin context, exact package path, runtime
  interpretation, and expected output files,
- the gallery page gives the stable rendered figures and their reading order.

What still remains outside this page is a broader Nancon postprocess family of
MF6-style bundle figures such as one compact flow-state triptych or support
overview. The current committed Nancon gallery case emphasizes hydrographic and
active-network diagnostics instead.

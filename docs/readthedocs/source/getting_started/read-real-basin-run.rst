Read One Real Basin Run
=======================

This page sits between the editable walkthroughs and the static capability
gallery.

Use it when you already understand how to launch one simulation, and now want
to read one **committed, versioned basin result page** without confusing:

- basin setup,
- support construction,
- solver state,
- and published documentation assets.

Stable Reference Runs
---------------------

The current documentation now contains three useful committed basin runs:

- :doc:`../capability_gallery/cases/modflow6_gmsh_mesh_catchment`
  for a **runtime-meshed** MODFLOW 6 case
- :doc:`../capability_gallery/cases/headwater_100km2_outlet_2_mf6_transient_reference`
  for a **committed-mesh replay**
- :doc:`../capability_gallery/cases/nancon_transient_nwt`
  for an **observed-basin transient NWT diagnostic case**

They do not answer exactly the same question.

.. list-table::
   :header-rows: 1
   :widths: 28 30 42

   * - Case family
     - Best first question
     - What the page is mainly teaching
   * - Runtime mesh build
     - "What support did the run actually build and consume?"
     - Mesh construction, support diagnostics, and first solver synthesis on a runtime support
   * - Committed mesh replay
     - "How does one stable basin replay behave once the support is already fixed?"
     - Solver response, cumulative forcing/discharge reading, and direct map interpretation on a versioned support
   * - Observed basin diagnostics
     - "How does one real basin run connect hydrography, active drainage patterns, and integrated response?"
     - Reference-vs-generated hydrography, simulated active-network overlap, then classical solver figures on one observed basin

Read The Figures In This Order
------------------------------

1. Support overview
2. Flow-state triptych
3. Direct water-table maps
4. Cumulative recharge/discharge

If you reverse that order, it becomes too easy to over-interpret one curve
before checking whether the support and state fields are even coherent.

1. Support Overview
-------------------

Start with the support, not the solver curve.

.. figure:: /_static/capability_gallery/simulation/modflow6_gmsh_support_overview.png
   :alt: Support overview for one committed real-basin simulation page
   :width: 100%

   Runtime support overview from the committed MODFLOW 6 plus Gmsh basin case.

Read this figure to answer:

- what mesh or grid the solver actually consumed,
- whether hydrography and support labels are where you expect,
- whether the run is a runtime-mesh build or a replay on a saved support.

Do **not** use this figure to decide whether the physics is already correct.
Its role is structural first.

2. Flow-State Triptych
----------------------

Only after the support looks coherent should you read the first solver-state
summary.

.. figure:: /_static/capability_gallery/simulation/modflow6_gmsh_flow_state_triptych.png
   :alt: Flow-state triptych for one committed real-basin simulation page
   :width: 100%

   Topography, hydraulic head, and water-table depth on the same real-basin support.

This is usually the highest-value single figure because it aligns:

- topography,
- simulated head,
- and water-table depth

on the same support.

Use it to ask:

- does the hydraulic state follow the basin structure sensibly?
- are shallow and deep zones where they should be?
- do surprising areas come from forcing, parameters, or the support itself?

3. Direct Water-Table Maps
--------------------------

When the triptych shows something interesting, isolate the variable before
making claims.

.. tab-set::

   .. tab-item:: Water-Table Elevation

      .. figure:: /_static/capability_gallery/simulation/headwater_100km2_outlet_2_mf6_transient_reference_watertable_elevation.png
         :alt: Water-table elevation on a committed real-basin replay
         :width: 100%

         Direct water-table elevation map from the committed headwater replay.

   .. tab-item:: Water-Table Depth

      .. figure:: /_static/capability_gallery/simulation/headwater_100km2_outlet_2_mf6_transient_reference_watertable_depth.png
         :alt: Water-table depth on a committed real-basin replay
         :width: 100%

         Direct water-table depth map from the same replay.

The elevation map answers:

- where is the groundwater surface high or low in absolute terms?

The depth map answers:

- where is the groundwater surface close to the land surface?

Those are not the same question. A basin can have high heads and still deep
water tables where topography is also high.

4. Cumulative Recharge And Discharge
------------------------------------

Read the cumulative curve only after the maps.

.. figure:: /_static/capability_gallery/simulation/headwater_100km2_outlet_2_mf6_transient_reference_recharge_discharge_cumulative.png
   :alt: Cumulative recharge and discharge on a committed real-basin replay
   :width: 100%

   Cumulative recharge and discharge for the committed headwater transient replay.

This figure is best for:

- checking whether the forcing chronology and basin response stay coherent,
- comparing broad runoff/drainage behaviour across runs,
- reading integrated behaviour over the full time window.

It is **not** the best first figure for diagnosing one local spatial anomaly.

Runtime-Meshed Versus Committed-Mesh Pages
------------------------------------------

When two pages both look like "real basin simulation", separate these two
families immediately:

- **runtime-meshed page**
  :
  support creation is part of the workflow being documented
- **committed-mesh replay page**
  :
  support creation is already frozen, so the page is mostly about solver and
  forcing interpretation

That distinction changes what a discrepancy means.

If the support is built at runtime, one surprising map may come from:

- meshing constraints,
- refinement policy,
- support transfer,
- or solver behaviour.

If the support is already committed, the same surprise is more likely to come
from:

- forcing,
- parameters,
- package semantics,
- or solver behaviour.

Where The Stable Assets Come From
---------------------------------

The committed pages above are backed by versioned asset folders under:

- ``examples/projects/09_capability_gallery/launcher_simulation/modflow6_gmsh_mesh_catchment/``
- ``examples/projects/09_capability_gallery/launcher_simulation/headwater_100km2_outlet_2_mf6_transient_reference/``
- ``examples/projects/09_capability_gallery/launcher_simulation/nancon_transient_nwt/``

Each folder contains a ``manifest.json`` that records at least:

- ``run_id``
- ``source_run_folder``
- ``solvers``
- copied asset filenames

This is the key bridge between "one heavy runtime folder" and "one stable RTD
page".

One practical nuance:

- several already-committed simulation cases use a manifest with schema
  ``v1``
- the current publisher code in
  ``hydromodpy/analysis/capability_gallery.py`` writes schema ``v2``

The user-facing contract is still the same:

- selected figures are copied or rendered into a versioned folder,
- one manifest records provenance,
- the doc page then points only to those committed assets.

How To Promote A New Run Into The Gallery
-----------------------------------------

The stable user-side pattern is:

1. run one case normally,
2. enable one ``[capability_gallery]`` block in the TOML,
3. select the PNG assets worth publishing,
4. rerun and commit the resulting asset folder plus ``manifest.json``.

Minimal example:

.. code-block:: toml

   [capability_gallery]
   enabled = true
   output_dir = "examples/projects/09_capability_gallery/launcher_simulation/my_basin_case"
   case_slug = "my_basin_case"
   assets = [
       "flow_support_overview.png",
       "flow_state_triptych.png",
       "watertable_elevation.png",
       "watertable_depth.png",
       "recharge_discharge_cumulative.png",
   ]

The important rule is not the exact filenames. It is this:

- choose assets that actually exist in the run figure folder,
- or assets that the runtime can render through the capability-gallery
  publisher.

For the current public simulation pages, the typical publication source is a
run folder figure directory such as ``_postprocess/_figures/`` and the
publisher writes a stable ``manifest.json`` next to the copied PNGs.

Nancon Status
-------------

The new scientific worked case
:doc:`../scientific/solvers/worked-modflow-case-nancon-transient-nwt-etp-evt`
explains the **package path** for a real Nancon MODFLOW-NWT run, and the new
gallery page :doc:`../capability_gallery/cases/nancon_transient_nwt` now adds
one stable committed result page for the same public example.

The current Nancon coverage is therefore split on purpose:

- the scientific worked case explains how the run is assembled and why `ETP`
  becomes `EVT`,
- the capability-gallery case explains how to read the committed basin figures,
- this page explains where that case sits relative to the other real-basin
  simulation pages.

What is still missing is a broader Nancon postprocess family with the same
compact `flow_state_triptych / support_overview / cumulative` bundle used by
some MF6 gallery cases. The current committed Nancon page emphasizes
hydrographic-network diagnostics instead.

Where To Go Next
----------------

- Use :doc:`simulation-walkthrough` when you want the editable run path.
- Use :doc:`reading-results-pages` when you want to distinguish walkthrough,
  comparison, validation, and gallery pages more generally.
- Use :doc:`../capability_gallery/simulation` when you want to browse the full
  current simulation gallery.

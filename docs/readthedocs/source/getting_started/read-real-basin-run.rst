Read One Real Basin Run
=======================

The previous versions of this page mixed several gallery families.

That was not a good teaching page if the real question is:

   "What does one actual basin run give me back, and what can I
   inspect or extract from it?"

This page now uses one single run as the reference example:

- :doc:`../capability_gallery/cases/nancon_transient_nwt`

Why This Example Is Better
--------------------------

The Nancon transient NWT run is a better onboarding case than the older mixed
"real basin" page because it exposes several kinds of retrievable data at
once:

- one observed basin,
- one public project folder,
- one transient MODFLOW-NWT run,
- one observed discharge series,
- one reference hydrographic network,
- one generated hydrographic network,
- one active-network diagnostic derived from the simulated state,
- one committed capability-gallery page for stable reading.

So this page is not mainly about "which picture looks nice".

It is about:

- what the run stores,
- what the Python API can recover,
- and which outputs are actually useful when the scientific question changes.

Reference Case
--------------

Use these two pages together:

- :doc:`../capability_gallery/cases/nancon_transient_nwt`
- :doc:`../scientific/solvers/worked-modflow-case-nancon-transient-nwt-etp-evt`

The gallery page is the committed visual reading path.

The scientific page explains why this run builds ``EVT`` at all and how
``data.etp`` reaches the MODFLOW-NWT package layer.

Visual Reading Path
-------------------

The same run can be read directly from the figures below. The full reference
page remains :doc:`../capability_gallery/cases/nancon_transient_nwt`; this
page reuses only the figures needed to connect the result to the Python
inventory.

.. figure:: /_static/capability_gallery/simulation/nancon_transient_nwt_hydrographic_network_comparison.png
   :alt: Reference and generated hydrographic networks on the Nancon basin
   :width: 100%

   Start with the two hydrographic networks. This tells you whether the
   generated structural network and the observed reference network are close
   enough before interpreting simulated drainage.

.. figure:: /_static/capability_gallery/simulation/nancon_transient_nwt_simulated_active_network_reference_overlay.png
   :alt: Simulated active network compared with observed hydrography on Nancon
   :width: 100%

   The active-network overlay is a simulation result, not an input layer. It
   turns stored drainage fluxes into a spatial diagnostic that can be compared
   with observed hydrography.

.. figure:: /_static/capability_gallery/simulation/nancon_transient_nwt_piezometric_map.png
   :alt: Piezometric map for the Nancon transient NWT run
   :width: 100%

   The piezometric map is the first groundwater-state figure to inspect when a
   spatial diagnostic looks surprising.

.. figure:: /_static/capability_gallery/simulation/nancon_transient_nwt_hydrograph.png
   :alt: Observed and simulated hydrograph for the Nancon transient NWT run
   :width: 100%

   The hydrograph moves from spatial state to basin response. It is the compact
   view of how the simulated outlet discharge compares with the observed
   chronicle.

.. figure:: /_static/capability_gallery/simulation/nancon_transient_nwt_water_budget.png
   :alt: Water budget for the Nancon transient NWT run
   :width: 100%

   The water budget closes the reading path: it explains which inflow and
   outflow components produced the simulated response.

Inventory Of Retrievable Data
-----------------------------

The current committed Nancon run exposes the following categories.

.. figure:: /_static/concepts/results/run_inventory.svg
   :alt: Inventory map of data families exposed by one persisted HydroModPy run
   :width: 100%

   Use this figure as the reading map for the table below. The committed
   gallery shows selected result figures; the persisted run also exposes
   fields, time series, budgets, geographic layers, metrics, and provenance.

.. list-table::
   :header-rows: 1
   :widths: 24 34 42

   * - Category
     - Current Nancon inventory
     - Main access path
   * - Provenance inputs
     - ``etp:etp``, ``hydrometry:discharge``, ``recharge:recharge``, ``runoff:runoff``
     - ``run.provenance``
   * - Geographic features
     - ``watershed``, ``watershed_box_buff``, ``watershed_contour``, ``hydrographic_network_reference``, ``hydrographic_network_generated``
     - ``run.geographic(...)`` and ``run.hydrographic_network(...)``
   * - Geographic rasters
     - ``watershed_dem``, ``watershed_fill``
     - ``run.geographic_raster(...)``, ``run.dem``, ``run.catchment_mask``
   * - Raw solver field
     - ``head``
     - ``run.field(\"head\", timestep=...)``
   * - Derived spatial fields
     - ``watertable_elevation``, ``watertable_depth``, ``accumulation_flux``, ``outflow_drain``, ``seepage_areas``
     - ``run.field(...)`` or ``run.fields(...)``
   * - Budget rasters / components
     - ``constant head``, ``drains``, ``et``, ``flow front face``, ``flow right face``, ``recharge``, ``storage``
     - ``run.budget(...)`` and Zarr ``budget/``
   * - Mass-balance table
     - total in/out, storage in/out, percent error
     - ``run.mass_balance``
   * - Time series
     - simulated ``_catchment / discharge`` and observed ``NANCON / discharge_obs``
     - ``run.timeseries(variable, station=...)``
   * - Derived series
     - catchment means of stored fields, plus recharge forcing
     - ``run.catchment_mean(...)`` and ``run.recharge_forcing()``
   * - Hydrography metrics
     - reference-vs-generated length and coverage metrics
     - ``run.hydrographic_network_comparison_metrics()``
   * - Active-network overlap metrics
     - overlap, coverage, precision, F1, Jaccard against reference hydrography
     - ``run.simulated_active_network_overlap_metrics()``
   * - Pre-rendered figures
     - ``piezometric_map``, ``water_budget``, ``hydrograph``, ``simulated_active_network``, ``simulated_active_network_reference_overlay``, and hydrographic-network figures
     - ``run.display_capabilities`` then ``run.plot(...)``

The key point is that the gallery page only shows a subset of this inventory.

The run itself gives you more than the committed figures.

Minimal Python Inventory
------------------------

.. code-block:: python

   from hydromodpy.project import Project

   project = Project("examples/projects/02_nancon_watershed/project.toml")
   run = project.runs.latest()

   print(run.display_capabilities)
   print(run.provenance)
   print(run.budget().component.unique())
   print(run.mass_balance.columns)
   print(run.available_hydrographic_network_roles())

   q_sim = run.timeseries("discharge", station="_catchment")
   q_obs = run.timeseries("discharge_obs", station="NANCON")

   wt_depth = run.field("watertable_depth", timestep=-1)
   wt_depth_mean = run.catchment_mean("watertable_depth")
   recharge = run.recharge_forcing()

   hydro_metrics = run.hydrographic_network_comparison_metrics()
   active_metrics = run.simulated_active_network_overlap_metrics()

   project.close()

What This Run Really Shows Well
-------------------------------

This run is especially useful for four kinds of questions.

1. "What came in and out of the basin?"

- ``run.budget()``
- ``run.mass_balance``
- ``run.recharge_forcing()``

2. "How did the outlet response react in time?"

- ``run.timeseries("discharge", station="_catchment")``
- ``run.timeseries("discharge_obs", station="NANCON")``
- the committed ``hydrograph`` figure

3. "What did the groundwater state look like in space?"

- ``run.field("watertable_elevation", timestep=...)``
- ``run.field("watertable_depth", timestep=...)``
- ``run.field("seepage_areas", timestep=...)``
- the committed ``piezometric_map`` figure

4. "How does the simulated drainage structure compare to observed hydrography?"

- ``run.hydrographic_network_comparison_metrics()``
- ``run.simulated_active_network_overlap_metrics()``
- the committed ``hydrographic_network_comparison`` figure
- the committed ``simulated_active_network_reference_overlay`` figure

If The Question Is EVT
----------------------

If the scientific question is specifically:

   "What is the effect of activating EVT on this basin?"

then the first outputs to inspect are **not** the same as for a generic basin
walkthrough.

Use this order instead:

1. ``run.budget(component="et")`` and ``run.budget(component="drains")``
2. ``run.timeseries("discharge", station="_catchment")``
3. ``run.catchment_mean("watertable_depth")``
4. timestep maps of ``watertable_depth``, ``outflow_drain``, and ``seepage_areas``
5. only then the active-network overlay and hydrographic metrics

Why this order matters:

- ``ET`` and ``DRN`` are the two outflow channels most likely to trade off
  against each other when EVT changes.
- the hydrograph tells you whether the basin-integrated response changes in a
  way that matters for calibration or interpretation.
- catchment-mean water-table depth tells you whether the basin dries slightly
  everywhere or strongly in a few places.
- spatial maps tell you where the shift actually happens.
- the hydrographic overlays are useful, but they are too downstream to be the
  first EVT diagnostic.

Recommended EVT Sensitivity Ladder
----------------------------------

If the goal is to make the effect of EVT visible in the documentation, one
single run is not enough.

The cleanest mini-study is:

1. **No EVT**
   :
   ``flow.active_sinks_sources = ["recharge"]``
2. **Baseline EVT**
   :
   ``flow.active_sinks_sources = ["recharge", "etp"]``
3. **Shallow EVT**
   :
   same as baseline, but with a smaller ``surface_offset`` and
   ``extinction_depth`` in ``[flow.sinks_sources.etp]``
4. **Deeper EVT**
   :
   same as baseline, but with a larger ``extinction_depth``

For example, the explicit runtime block could be documented as:

.. code-block:: toml

   [flow.sinks_sources.etp]
   surface_offset = 0.5
   extinction_depth = 0.5

or:

.. code-block:: toml

   [flow.sinks_sources.etp]
   surface_offset = 2.0
   extinction_depth = 3.0

The first comparison to publish should be **No EVT vs Baseline EVT**.

Only after that should the docs add a second layer about
``surface_offset / extinction_depth`` sensitivity.

What The Current Docs Still Do Not Show Well
--------------------------------------------

The current RTD pages still do not make three things visible enough:

- that one real run exposes a richer API than the committed figures alone,
- that ``ET`` can be analysed as a budget component and not only as a package
  name in the scientific text,
- that one EVT sensitivity study should be read primarily through
  budget / hydrograph / water-table diagnostics before any fancy overlay map.

That is the right base to improve next.

Where To Go Next
----------------

- Use :doc:`../capability_gallery/cases/nancon_transient_nwt` for the stable
  committed figures.
- Use :doc:`../scientific/solvers/worked-modflow-case-nancon-transient-nwt-etp-evt`
  for the package-path explanation.
- Use :doc:`reading-results-pages` if you want to distinguish gallery pages,
  validation pages, and comparison pages more generally.

Network Metrics And Extreme K-Sweep
===================================

Purpose
-------

This page separates three notions that are easy to confuse:

- ``reference`` is the observed hydrographic network loaded with the run.
- ``persistent`` is the transient simulated-active extraction mode used in
  the examples below: a cell is retained when it is active for at least 50% of
  the simulated timesteps.
- ``steady`` is a flow regime. A steady active network should come from a
  ``flow_regime = "steady"`` run, not from a transient persistence rule.

The extreme K-sweep below is therefore a transient sensitivity experiment.
It compares a persistent simulated-active network with the observed
``reference`` network.

Metric Families
---------------

HydroModPy currently exposes three modern metric families for stream-network
diagnostics.

.. list-table::
   :header-rows: 1
   :widths: 22 28 28 22

   * - Family
     - What is compared?
     - Current implementation
     - Relation to Abherve et al. (2023)
   * - Vector linework overlap
     - ``reference`` vector network versus another vector network, usually
       ``generated``
     - ``run.hydrographic_network_comparison()``
     - Different: it compares vector linework with a tolerance buffer, not
       simulated seepage cells routed downslope.
   * - Simulated-active cell overlap
     - simulated active cells versus the observed ``reference`` network
       rasterized onto mesh cells
     - ``run.simulated_active_network_overlap_metrics()``
     - Compatible as a first diagnostic, but different from the article: it
       measures cell overlap, coverage, precision, F1 and Jaccard.
   * - Simulated-active planar distance
     - active simulated cells versus the observed ``reference`` network, in
       both directions
     - ``run.simulated_active_network_distance_metrics()``
     - Intermediate: it measures planar cell-centroid distances and is
       explicitly not the downslope DEM-routing metric from the article.
   * - Legacy matching streams
     - observed stream raster versus simulated seepage raster, in both
       directions
     - historically implemented as ``MatchingStreams`` in
       ``hydromodpy/analysis/postprocess/flow/matching_streams.py``
     - Closest conceptual match: it created downslope-distance rasters and
       point samples needed to compute the bidirectional criterion.

The legacy ``MatchingStreams`` code did not persist a clean scalar CSV with
``D_so``, ``D_os`` and ``D_optim``. It produced the artifacts needed to derive
them:

- ``obs.tif`` and ``sim.tif``: observed and simulated stream supports.
- ``obsflow.tif`` and ``simflow.tif``: traced downslope flowpaths.
- ``dist_dem_obs.tif`` and ``dist_dem_sim.tif``: downslope-distance rasters.
- sampled point layers such as ``sim_pt.shp`` and ``obs_pt.shp``.

To make it fully compatible with Abherve et al. (2023), HydroModPy should
modernize that logic into a result view and CSV export that computes at least:

- ``D_so``: average simulated-to-observed downslope distance.
- ``D_os``: average observed-to-simulated downslope distance.
- ``D_optim``: combined distance criterion.
- ``r_optim``: ``D_optim`` normalized by the DEM or analysis resolution.

Current Extreme Sweep
---------------------

The sweep is centered on ``K = 2e-4 m/s`` and adds hydraulic conductivities
that are 10 and 100 times lower and higher.

.. list-table::
   :header-rows: 1
   :widths: 18 18 28 36

   * - Variant
     - K
     - Factor vs reference
     - Interpretation
   * - ``k_2e6``
     - ``2e-6 m/s``
     - ``0.01x``
     - very low-K saturated stress test
   * - ``k_2e5``
     - ``2e-5 m/s``
     - ``0.1x``
     - low-K branch
   * - ``k_2e4``
     - ``2e-4 m/s``
     - ``1x``
     - reference variant for this sweep
   * - ``k_2e3``
     - ``2e-3 m/s``
     - ``10x``
     - high-K branch; this stress test failed to converge in the run below
   * - ``k_2e2``
     - ``2e-2 m/s``
     - ``100x``
     - very high-K dry stress test

Run Command
-----------

From the repository root:

.. code-block:: powershell

   hmp run examples/projects/09_comparison_workflow/compare_nancon_transient_seasonal_hydrography_extreme_k_sweep_mf6_only.toml

The run writes results under:

.. code-block:: text

   examples/projects/09_comparison_workflow/outputs/nancon_transient_seasonal_hydrography_extreme_k_sweep_mf6/

The most useful files are:

- ``simulated_active_network_metrics.csv``
- ``simulated_active_network_overlap_metrics.csv``
- ``simulated_active_network_distance_metrics.csv``
- ``run_figures/<variant>/simulated_active_network_reference_overlay.png``
- ``comparison_report.md``
- ``comparison_audit.md``

Case Configuration
------------------

.. figure:: /_static/workflows/simulated_active_network/nancon_extreme_k_sweep/case_configuration.png
   :alt: Nancon extreme K-sweep comparison configuration
   :width: 100%

   Common comparison support for the extreme MODFLOW 6 variants.

Run Status
----------

Four variants completed and one failed:

- ``k_2e6`` completed in 4.63 min.
- ``k_2e5`` completed in 3.84 min.
- ``k_2e4`` completed in 5.34 min.
- ``k_2e3`` failed by MODFLOW 6 non-convergence at stress period 37.
- ``k_2e2`` completed in 16.25 min.

The failed ``k_2e3`` case is kept in the design table because it is
scientifically informative: the high-K branch is numerically stiff for this
setup and should not be treated as a calibrated production case without
solver/settings review.

Overlap Metrics
---------------

The table below uses the current cell-overlap metrics. It is intentionally not
presented as the Abherve et al. distance criterion.

.. list-table::
   :header-rows: 1
   :widths: 12 14 15 13 13 11 11 11

   * - Variant
     - K
     - Active cells
     - Missing ref.
     - Extra active
     - Coverage
     - Precision
     - F1
   * - ``k_2e6``
     - ``2e-6``
     - 3033
     - 302
     - 1656
     - 0.820
     - 0.454
     - 0.584
   * - ``k_2e5``
     - ``2e-5``
     - 1496
     - 788
     - 612
     - 0.529
     - 0.591
     - 0.558
   * - ``k_2e4``
     - ``2e-4``
     - 811
     - 1164
     - 301
     - 0.305
     - 0.629
     - 0.410
   * - ``k_2e2``
     - ``2e-2``
     - 174
     - 1579
     - 73
     - 0.060
     - 0.580
     - 0.109

Planar Distance Metrics
-----------------------

The table below is produced by
``simulated_active_network_distance_metrics.csv``. It is a planar
cell-centroid diagnostic. It is useful for reading the existing sweep, but it
does not replace the downslope DEM-routing metric described below.

.. list-table::
   :header-rows: 1
   :widths: 12 14 18 18 18 18

   * - Variant
     - K
     - Sim -> ref mean m
     - Ref -> sim mean m
     - Bidirectional mean m
     - Quadratic mean m
   * - ``k_2e6``
     - ``2e-6``
     - 310.7
     - 10.1
     - 160.4
     - 310.8
   * - ``k_2e5``
     - ``2e-5``
     - 292.4
     - 52.7
     - 172.6
     - 297.1
   * - ``k_2e4``
     - ``2e-4``
     - 321.8
     - 253.8
     - 287.8
     - 409.8
   * - ``k_2e2``
     - ``2e-2``
     - 94.1
     - 2139.5
     - 1116.8
     - 2141.6

Visual Sweep
------------

``K = 2e-6 m/s``: 100x lower than reference
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. figure:: /_static/workflows/simulated_active_network/nancon_extreme_k_sweep/k_2e6_reference_overlay.png
   :alt: Simulated active network versus reference network for K equals 2e-6 m/s
   :width: 100%

``K = 2e-5 m/s``: 10x lower than reference
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. figure:: /_static/workflows/simulated_active_network/nancon_extreme_k_sweep/k_2e5_reference_overlay.png
   :alt: Simulated active network versus reference network for K equals 2e-5 m/s
   :width: 100%

``K = 2e-4 m/s``: reference variant
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. figure:: /_static/workflows/simulated_active_network/nancon_extreme_k_sweep/k_2e4_reference_overlay.png
   :alt: Simulated active network versus reference network for K equals 2e-4 m/s
   :width: 100%

``K = 2e-2 m/s``: 100x higher than reference
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. figure:: /_static/workflows/simulated_active_network/nancon_extreme_k_sweep/k_2e2_reference_overlay.png
   :alt: Simulated active network versus reference network for K equals 2e-2 m/s
   :width: 100%

There is no figure for ``k_2e3`` because the MODFLOW 6 solve did not converge.

Current Reading
---------------

The current metric should be read as a diagnostic of network support
co-location on the model mesh:

- high coverage means the simulated active network captures much of the
  observed ``reference`` network;
- high precision means simulated active cells mostly fall near the observed
  ``reference`` network;
- missing reference cells diagnose under-development of the simulated active
  network;
- extra active cells diagnose over-development or active cells away from the
  observed network.

The article-style distance metric would add directional distance information:
how far simulated seepage must be routed to reach observed streams, and how far
observed streams are from simulated seepage. That is the next implementation
step if this diagnostic is promoted from visual development to calibration.

The current code now adds a safer intermediate CSV,
``simulated_active_network_distance_metrics.csv``. It contains:

- ``sim_to_network_*``: distances from active simulated cell centroids to the
  selected network role, usually ``reference``;
- ``network_to_sim_*``: distances from cells intersected by the selected
  network to the union of active simulated cells;
- ``bidirectional_distance_mean_m`` and
  ``bidirectional_distance_quadratic_mean_m`` as compact symmetric summaries;
- ``distance_method = "planar_cell_centroid_to_network"`` to make clear that
  these are planar mesh diagnostics, not downslope DEM distances.

Related Reading
---------------

- :doc:`nancon-k-sweep-results`
- :doc:`conceptual-model`
- :doc:`../hydrology/simulated-active-network`
- Abherve, R. et al. (2023), `Calibration of groundwater seepage against the
  spatial distribution of the stream network to assess catchment-scale
  hydraulic properties <https://doi.org/10.5194/hess-27-3221-2023>`_.

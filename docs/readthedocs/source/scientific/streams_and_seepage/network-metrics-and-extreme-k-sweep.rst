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

- :math:`D^{down}_{s\to o}`: average simulated-to-observed downslope
  distance.
- :math:`D^{down}_{o\to s}`: average observed-to-simulated downslope
  distance.
- :math:`D_{optim}`: combined downslope-distance criterion.
- :math:`r_{optim}`: :math:`D_{optim}` normalized by the DEM or analysis
  resolution.

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

After rerunning the workflow, refresh the committed documentation figures with:

.. code-block:: powershell

   python docs/readthedocs/source/scientific/streams_and_seepage/diagrams/render_nancon_k_sweep_doc_figures.py --sweep extreme

The script reads the exported CSV metrics and recomposes the map figures with
their metric bands, then writes the trend and tradeoff graphs shown below.

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

Metric Notation
---------------

The generated figures use compact notation so the map and metrics can be read
together:

- :math:`N_a`: persistent simulated-active cells.
- :math:`N_{ref}`: cells intersected by the observed ``reference`` network.
- :math:`N_{ov}`: overlap cells, active and reference at the same time.
- :math:`N_{miss}`: reference cells not captured by simulated activity.
- :math:`N_{extra}`: active cells outside the reference-network support.
- :math:`C_{ref}=N_{ov}/N_{ref}`: reference-network coverage.
- :math:`P_a=N_{ov}/N_a`: simulated-active precision.
- :math:`F_1=2 C_{ref} P_a/(C_{ref}+P_a)`: harmonic overlap score.
- :math:`D^{plan}_{s\to ref}`: simulated-active to observed-reference
  planar distance.
- :math:`D^{plan}_{ref\to s}`: observed-reference to simulated-active
  planar distance.
- :math:`\bar{D}^{plan}`: symmetric mean of those two directional planar
  distances.
- :math:`R_D^{plan}=D^{plan}_{s\to ref}/D^{plan}_{ref\to s}`:
  planar distance-balance ratio. It is the current proxy for reading an
  optimum-like crossing; the article uses downslope distances instead.

Visual Sweep
------------

Each map below is regenerated from the workflow outputs by
``render_nancon_k_sweep_doc_figures.py``. The metric band is intentionally
placed below the map so the spatial pattern and scalar diagnostics stay
together.

``K = 2e-6 m/s``: 100x lower than reference
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. figure:: /_static/workflows/simulated_active_network/nancon_extreme_k_sweep/k_2e6_reference_overlay.png
   :alt: Simulated active network versus reference network for K equals 2e-6 m/s
   :width: 100%

   ``k_2e6``: :math:`N_a=3033`, :math:`C_{ref}=0.820`,
   :math:`P_a=0.454`, :math:`F_1=0.584`,
   :math:`\bar{D}^{plan}=160` m.

``K = 2e-5 m/s``: 10x lower than reference
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. figure:: /_static/workflows/simulated_active_network/nancon_extreme_k_sweep/k_2e5_reference_overlay.png
   :alt: Simulated active network versus reference network for K equals 2e-5 m/s
   :width: 100%

   ``k_2e5``: :math:`N_a=1496`, :math:`C_{ref}=0.529`,
   :math:`P_a=0.591`, :math:`F_1=0.558`,
   :math:`\bar{D}^{plan}=173` m.

``K = 2e-4 m/s``: reference variant
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. figure:: /_static/workflows/simulated_active_network/nancon_extreme_k_sweep/k_2e4_reference_overlay.png
   :alt: Simulated active network versus reference network for K equals 2e-4 m/s
   :width: 100%

   ``k_2e4``: :math:`N_a=811`, :math:`C_{ref}=0.305`,
   :math:`P_a=0.629`, :math:`F_1=0.410`,
   :math:`\bar{D}^{plan}=288` m.

``K = 2e-2 m/s``: 100x higher than reference
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. figure:: /_static/workflows/simulated_active_network/nancon_extreme_k_sweep/k_2e2_reference_overlay.png
   :alt: Simulated active network versus reference network for K equals 2e-2 m/s
   :width: 100%

   ``k_2e2``: :math:`N_a=174`, :math:`C_{ref}=0.060`,
   :math:`P_a=0.580`, :math:`F_1=0.109`,
   :math:`\bar{D}^{plan}=1117` m.

There is no figure for ``k_2e3`` because the MODFLOW 6 solve did not converge.

Metric Evolution
^^^^^^^^^^^^^^^^

.. figure:: /_static/workflows/simulated_active_network/nancon_extreme_k_sweep/metric_trends.png
   :alt: Evolution of Nancon extreme K-sweep active-network metrics with hydraulic conductivity
   :width: 100%

   Evolution of support size, overlap quality, planar distance metrics, and
   :math:`\log_{10} R_D^{plan}` across the completed extreme ``K`` values.
   Crossing 0 marks a planar balance between the two directional distances.
   The failed ``k_2e3`` solve is excluded from the curve because no valid
   simulated-active network was produced for that variant.

.. figure:: /_static/workflows/simulated_active_network/nancon_extreme_k_sweep/metric_tradeoff.png
   :alt: Nancon extreme K-sweep overlap and distance tradeoff graph
   :width: 100%

   Tradeoff view: coverage versus precision, then
   :math:`\bar{D}^{plan}` versus :math:`F_1`. Point size is proportional to
   :math:`N_a`.

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

The current planar metrics do contain an optimum-style balance proxy:
``planar_distance_balance_ratio`` and ``planar_distance_log10_balance``. The
proxy is useful for inspecting whether the two directional distances cross as
``K`` changes. It is not :math:`r_{optim}` from Abherve et al. (2023), because
the paper computes :math:`D_{optim}` from downslope flowpath distances and then
normalizes it by the DEM resolution.

The current code now adds a safer intermediate CSV,
``simulated_active_network_distance_metrics.csv``. It contains:

- ``sim_to_network_*``: :math:`D^{plan}_{s\to ref}` distances from active
  simulated cell centroids to the selected network role, usually
  ``reference``;
- ``network_to_sim_*``: :math:`D^{plan}_{ref\to s}` distances from cells
  intersected by the selected network to the simulated-active support;
- ``bidirectional_distance_mean_m`` and
  ``bidirectional_distance_quadratic_mean_m`` as compact symmetric planar
  summaries;
- ``planar_distance_balance_ratio`` and
  ``planar_distance_log10_balance`` as the current planar crossing proxy;
- ``distance_method = "planar_cell_centroid_to_network"`` to make clear that
  these are planar mesh diagnostics, not downslope DEM distances.

Related Reading
---------------

- :doc:`nancon-k-sweep-results`
- :doc:`conceptual-model`
- :doc:`../hydrology/simulated-active-network`
- Abherve, R., Roques, C., Gauvain, A., Longuevergne, L., Louaisil, S.,
  Aquilina, L., and de Dreuzy, J.-R. (2023), `Calibration of groundwater
  seepage against the spatial distribution of the stream network to assess
  catchment-scale hydraulic properties
  <https://doi.org/10.5194/hess-27-3221-2023>`_, Hydrol. Earth Syst. Sci.,
  27, 3221-3239.

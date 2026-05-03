Nancon K-Sweep Results
======================

Purpose
-------

This page keeps one concrete simulation result close to the streams and
seepage concepts. It is not a calibration result. It is a visual and numerical
development case used to inspect how the simulation-derived active network
changes when hydraulic conductivity varies.

This is the MODFLOW 6 real-basin example for the conceptual sequence:

.. code-block:: text

   solved head -> local drain/seepage outflow -> accumulation_flux
   -> persistent simulated-active mask -> overlap against reference

Use it after :doc:`conceptual-model` and :doc:`worked-examples`, not before.
The conceptual pages explain why the active network is a diagnostic derived
from seepage or drainage outflow, while this page shows how that diagnostic
behaves in one concrete parameter sweep.

The comparison target is the observed ``reference`` hydrographic network. If a
run has no ``reference`` network, the simulated-active overlap comparison is
skipped; HydroModPy does not silently compare against the DEM-derived
``generated`` network.

Parameter Range
---------------

This sweep is aligned with the higher-conductivity Nancon parameter examples,
especially the ``F`` family in
``examples/projects/09_comparison_workflow/run_nancon_parameter_sweep.py``.
The range is deliberately widened around that family so that the visual
sensitivity of the simulated active network is easier to inspect.

The sweep uses:

- ``K = 5e-5, 1e-4, 2e-4, 5e-4 m/s``
- ``Ss = 1e-4 m-1``
- ``Sy = 0.05``
- drainage conductance ``= 3e-3 m2/s``
- ``modflow6.tgrid.firstpersteady = false``

``k_2e4`` is only the reference variant for head-map difference plots. The
stream comparison below always compares each simulated-active network against
the observed ``reference`` hydrographic network.

Run Command
-----------

From the repository root:

.. code-block:: powershell

   python examples/projects/09_comparison_workflow/run_comparison_example.py --case nancon-seasonal-hydrography-k-sweep-mf6

The run writes results under:

.. code-block:: text

   examples/projects/09_comparison_workflow/outputs/nancon_transient_seasonal_hydrography_wide_k_sweep_mf6/

The main files to inspect are:

- ``simulated_active_network_metrics.csv``
- ``simulated_active_network_overlap_metrics.csv``
- ``simulated_active_network_distance_metrics.csv``
- ``run_figures/<variant>/simulated_active_network_reference_overlay.png``
- ``comparison_report.md``
- ``comparison_audit.md``

Case Configuration
------------------

.. figure:: /_static/workflows/simulated_active_network/nancon_wide_k_sweep/case_configuration.png
   :alt: Nancon wide-K sweep comparison configuration
   :width: 100%

   Common comparison support for the four MODFLOW 6 variants.

Variants
--------

.. list-table::
   :header-rows: 1
   :widths: 18 18 64

   * - Variant
     - K
     - Interpretation
   * - ``k_5e5``
     - ``5e-5 m/s``
     - wider saturated branch
   * - ``k_1e4``
     - ``1e-4 m/s``
     - low value from the higher-conductivity Nancon ``F`` family
   * - ``k_2e4``
     - ``2e-4 m/s``
     - middle value from the higher-conductivity Nancon ``F`` family
   * - ``k_5e4``
     - ``5e-4 m/s``
     - wider dry branch

Overlap Metrics
---------------

The table below compares the simulated active network of each variant against
the observed ``reference`` linework. The mode is ``persistent`` because this is
a transient run; cells active for at least 50% of timesteps are retained.

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
   * - ``k_5e5``
     - ``5e-5``
     - 1173
     - 955
     - 452
     - 0.430
     - 0.615
     - 0.506
   * - ``k_1e4``
     - ``1e-4``
     - 950
     - 1088
     - 367
     - 0.349
     - 0.614
     - 0.445
   * - ``k_2e4``
     - ``2e-4``
     - 812
     - 1177
     - 316
     - 0.296
     - 0.611
     - 0.399
   * - ``k_5e4``
     - ``5e-4``
     - 670
     - 1268
     - 250
     - 0.249
     - 0.627
     - 0.356

Planar Distance Metrics
-----------------------

The table below is produced by
``simulated_active_network_distance_metrics.csv``. It is a planar
cell-centroid diagnostic, not the downslope DEM-routing criterion.

.. list-table::
   :header-rows: 1
   :widths: 12 14 18 18 18 18

   * - Variant
     - K
     - Sim -> ref mean m
     - Ref -> sim mean m
     - Bidirectional mean m
     - Quadratic mean m
   * - ``k_5e5``
     - ``5e-5``
     - 295.5
     - 105.1
     - 200.3
     - 313.7
   * - ``k_1e4``
     - ``1e-4``
     - 321.1
     - 156.0
     - 238.5
     - 357.0
   * - ``k_2e4``
     - ``2e-4``
     - 332.1
     - 255.5
     - 293.8
     - 419.0
   * - ``k_5e4``
     - ``5e-4``
     - 319.4
     - 451.5
     - 385.4
     - 553.0

What To Read In These Metrics
-----------------------------

- Increasing ``K`` contracts the persistent simulated-active extent: active
  cells decrease from 1173 to 670.
- The contraction reduces extra active cells, but it also misses more of the
  observed reference network.
- Precision stays around 0.61, while coverage drops from 0.430 to 0.249.
- The planar bidirectional distance increases from 200 m to 385 m as the
  simulated active network contracts away from parts of the observed network.
- This confirms the visual effect requested for development: the simulated
  network is much less saturated than the earlier low-K sweep. It also shows
  that matching the observed linework will require a real calibration protocol,
  not only increasing ``K``.

Visual Sweep
------------

``K = 5e-5 m/s``: wider saturated branch
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. figure:: /_static/workflows/simulated_active_network/nancon_wide_k_sweep/k_5e5_reference_overlay.png
   :alt: Simulated active network versus reference network for K equals 5e-5 m/s
   :width: 100%

``K = 1e-4 m/s``: Nancon F low
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. figure:: /_static/workflows/simulated_active_network/nancon_wide_k_sweep/k_1e4_reference_overlay.png
   :alt: Simulated active network versus reference network for K equals 1e-4 m/s
   :width: 100%

``K = 2e-4 m/s``: Nancon F middle
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. figure:: /_static/workflows/simulated_active_network/nancon_wide_k_sweep/k_2e4_reference_overlay.png
   :alt: Simulated active network versus reference network for K equals 2e-4 m/s
   :width: 100%

``K = 5e-4 m/s``: wider dry branch
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. figure:: /_static/workflows/simulated_active_network/nancon_wide_k_sweep/k_5e4_reference_overlay.png
   :alt: Simulated active network versus reference network for K equals 5e-4 m/s
   :width: 100%

Current Limitation
------------------

This run is useful for visual development, but the audit is intentionally
strict and reports small mesh differences between variants. For a clean
K-only protocol, the next step is to freeze and reuse exactly the same mesh
for every variant, then rerun the same sweep.

The overlap metric is cell-based: it rasterizes the observed ``reference``
linework onto the model mesh and compares it with simulated active cells. The
new distance export adds a second, planar diagnostic based on bidirectional
cell-centroid distances. A future calibration metric should still add the
bidirectional downslope criterion used by Abherve et al. (2023), where the
simulated seepage network is compared to the observed stream network through
simulated-to-observed and observed-to-simulated flowpath distances.

Related Reading
---------------

- :doc:`index`
- :doc:`conceptual-model`
- :doc:`../hydrology/simulated-active-network`
- :doc:`../../getting_started/comparison-workflow`
- Abhervé, R. et al. (2023), `Calibration of groundwater seepage against the
  spatial distribution of the stream network to assess catchment-scale
  hydraulic properties <https://doi.org/10.5194/hess-27-3221-2023>`_.

Simulated Active Network
========================

Purpose
-------

The simulated active network is the part of the drainage support that becomes
active because of the groundwater-flow solution.

It is not loaded from an external river file and it is not the DEM-derived
``generated`` hydrographic network. It is a post-processed signal derived from
cell-by-cell simulated drainage outflow.

This page explains the three levels that should not be confused:

1. local drain outflow at each cell,
2. downstream accumulation of that outflow,
3. a thresholded or persistence-based active-network mask.

Quick Visual Reading
--------------------

Read the simulated active network from the groundwater state toward the
interpretation layer. The figure below is the shortest path through the
concept:

.. figure:: /_static/workflows/simulated_active_network/modflow6_active_network_four_panel.png
   :alt: Four-panel reading path from MODFLOW 6 head to drain outflow, accumulation flux, and simulated active network mask
   :width: 100%

   The practical reading order is: solved water table, local positive drain
   outflow, routed accumulation, then thresholded or persistent active-network
   view. Only the first two panels should be read as groundwater state or local
   flux. The last two panels are network diagnostics.

Conceptual Contract
-------------------

HydroModPy keeps the raw simulated drainage signal as cell fields before any
vector network is declared.

For a steady-network question, distinguish the steady-flow scenario from the
transient occupancy rule. A simulated steady active network should preferably
be derived from a representative ``flow_regime = "steady"`` run, then compared
with the observed ``reference`` network. The transient ``always_active`` mask
only means active at all timesteps of the analysed chronicle.

.. list-table::
   :header-rows: 1
   :widths: 22 34 44

   * - Field or view
     - Meaning
     - How to read it
   * - ``outflow_drain``
     - Positive groundwater discharge through drains, summed over model layers.
     - Local source term. A positive value means that groundwater leaves the
       aquifer through the drain condition in that cell.
   * - ``accumulation_flux``
     - Downstream accumulation of positive drain discharge.
     - Network signal. High values mark cells that receive upstream active
       drainage contributions.
   * - ``simulated_active_network_mask``
     - Boolean or continuous mask derived from ``accumulation_flux``.
     - Display and metric layer. The threshold must be explicit; the time rule
       is implicit for ``steady`` runs and explicit for ``transient`` runs.

The sign convention is intentionally normalized at the HydroModPy result level:
``outflow_drain`` is positive when water leaves the groundwater system. This is
different from raw MODFLOW cell-budget records, where leaving the aquifer is
usually stored with a negative sign.

The same contract can be read as a processing ladder:

.. uml:: diagrams/simulated_active_network_concept_ladder.wsd

The main safety rule is simple: ``outflow_drain`` is the local mass-exchange
quantity, while ``accumulation_flux`` is a routed network diagnostic. A
thresholded mask derived from ``accumulation_flux`` is a display or comparison
view, not a new observed river dataset.

Why Accumulation Is Not Just Another Drain Map
----------------------------------------------

``outflow_drain`` and ``accumulation_flux`` answer different questions.

``outflow_drain`` answers:

   "Where does the model release water locally through the drainage package?"

``accumulation_flux`` answers:

   "If local drainage contributions are routed downslope through the mesh, which
   cells form the connected active drainage structure?"

This distinction matters because a downstream cell may have a small local drain
outflow but a large accumulated flux if many upstream cells drain toward it. In
figures, this usually makes confluences and persistent branches easier to see.

Where This Page Fits In The Examples
------------------------------------

Use this page as the MODFLOW 6 result-contract example. It shows how a solver
run becomes an interpretable active-network diagnostic:

.. code-block:: text

   head -> outflow_drain -> accumulation_flux -> simulated_active_network

For the complete list of examples, commands, and files to open, see
:doc:`../streams_and_seepage/worked-examples`. For the current distinction
between supported fields, demonstrated examples, and non-contracts, see
:doc:`../streams_and_seepage/status-and-limitations`.

MODFLOW 6 Validation Example
----------------------------

The following figures come from a real MODFLOW 6 run executed through the
HydroModPy simulation workflow. The run has three stored timesteps and a
structured 60 x 60 MODFLOW 6 support. The MODFLOW 6 extractor writes the solver
mesh topology from the grid binary file, so the result layer can reshape fields
on the solver grid instead of forcing the original DEM shape.

The four-panel figure at the top of the page is the compact reading guide. The
individual panels below keep the legends large enough for detailed inspection.

.. figure:: /_static/workflows/simulated_active_network/modflow6_piezometric_map.png
   :alt: MODFLOW 6 water table map used as context for the simulated active network example
   :width: 80%

   Water-table field for the validation run. This is the groundwater state from
   which head-dependent drainage outflow is produced.

.. figure:: /_static/workflows/simulated_active_network/modflow6_outflow_drain_last.png
   :alt: Positive local MODFLOW 6 drain outflow on the last timestep
   :width: 80%

   ``outflow_drain`` on the last timestep. The field is local and positive:
   it shows where groundwater leaves the aquifer through the drain condition.

.. figure:: /_static/workflows/simulated_active_network/modflow6_accumulation_flux_last.png
   :alt: Downstream accumulated MODFLOW 6 drain outflow on the last timestep
   :width: 80%

   ``accumulation_flux`` on the last timestep. The spatial pattern follows
   the same active-drainage support, but values increase along downstream
   paths because upstream contributions are accumulated.

.. figure:: /_static/workflows/simulated_active_network/modflow6_simulated_active_network.png
   :alt: Thresholded simulated active network mask for the MODFLOW 6 validation run
   :width: 80%

   ``simulated_active_network`` figure. This is a computed cell-mask view
   produced from ``accumulation_flux``. It is useful for inspection and
   comparison, but it is not yet a stored vector line network.

For this validation run, the last timestep diagnostic summary was:

.. list-table::
   :header-rows: 1
   :widths: 30 18 18 18 16

   * - Field
     - Shape
     - Max
     - Sum
     - Non-zero cells
   * - ``outflow_drain``
     - ``(3, 60, 60)``
     - ``1.71e-3 m3/s``
     - ``9.16e-2 m3/s``
     - ``230``
   * - ``accumulation_flux``
     - ``(3, 60, 60)``
     - ``1.91e-2 m3/s``
     - ``5.54e-1 m3/s``
     - ``283``

Do not interpret the sum of ``accumulation_flux`` as a water-budget total. It
is a routed network diagnostic: the same upstream water contribution may be
counted again along downstream cells. Use budget tables and ``outflow_drain``
for mass-balance interpretation.

Current MODFLOW 6 Implementation Path
-------------------------------------

For ``flow/modflow6``, HydroModPy now uses the following result path:

1. MODFLOW 6 produces heads and budget components.
2. The output adapter reads the MODFLOW 6 grid binary file when available.
3. The catalog stores:

   - ``mesh/vertices``,
   - ``mesh/face_node_connectivity``,
   - ``mesh/surface_top``,
   - ``mesh/z_interfaces``.

4. The derived-field extractor converts raw DRN budget values to positive
   ``outflow_drain``.
5. The extractor computes ``accumulation_flux``:

   - structured D8 routing when a regular raster support is available,
   - mesh-graph downhill routing when a plottable face connectivity exists,
   - local positive outflow as a conservative fallback.

6. ``Run.fields(...)`` returns fields on the solver support when that support
   differs from the geographic DEM grid.
7. The display layer enables ``simulated_active_network`` when both
   ``accumulation_flux`` and plottable mesh topology are present.

The runtime path is:

.. uml:: diagrams/simulated_active_network_mf6_runtime.wsd

This is the implementation detail that makes MODFLOW 6 different from a simple
regular-raster postprocess. The solver support can be different from the source
DEM support, so the output adapter must persist enough mesh topology for later
views to know what each cell means.

Programmatic Reading
--------------------

After a run is available through ``Run``, inspect the fields directly:

.. code-block:: python

   acc = run.fields("accumulation_flux")
   drn = run.fields("outflow_drain")

   print(acc.shape)
   print(drn[-1].max())

Render the active-network figure when the capability is available:

.. code-block:: python

   if "simulated_active_network" in run.display_capabilities:
       run.plot("simulated_active_network", save="figures")

Compare the same active-network view against the observed ``reference``
network when that role exists:

.. code-block:: python

   overlap = run.simulated_active_network_overlap_metrics(
       network_role="reference",
       variable="accumulation_flux",
       mode="persistent",
       threshold=0.0,
       persistence_threshold=0.5,
   )

   distance = run.simulated_active_network_distance_metrics(
       network_role="reference",
       variable="accumulation_flux",
       mode="persistent",
       threshold=0.0,
       persistence_threshold=0.5,
   )

``overlap`` gives coverage, precision, F1 and Jaccard on mesh cells.
``distance`` gives bidirectional planar cell-centroid distances. It is a
current diagnostic, not the future downslope DEM-routing criterion.

For steady runs, do not pass a time mode unless you intentionally want to force
a diagnostic snapshot. The default is the steady-state active-network field:

.. code-block:: python

   mask = run.simulated_active_network_mask(
       variable="accumulation_flux",
       threshold=0.0,
   )

For transient runs, select the time rule explicitly:

.. code-block:: python

   mask = run.simulated_active_network_mask(
       variable="accumulation_flux",
       mode="persistent",
       threshold=0.0,
       persistence_threshold=0.5,
   )

The main modes are:

- ``last``: active cells on one timestep;
- ``any``: active at least once;
- ``persistent``: active for at least a declared fraction of timesteps;
- ``always_active``: active at every analysed timestep;
- ``persistence``: continuous active-time fraction.

``perennial`` is kept only as a legacy alias for ``always_active``. New
documentation and comparison work should use ``steady`` for the representative
steady-flow concept, and should compare the resulting active network with
``reference``. If no ``reference`` network is available, the validation
comparison should be skipped rather than falling back to ``generated``.

The transient modes can be read as:

.. uml:: diagrams/simulated_active_network_time_modes.wsd

What This Is Not Yet
--------------------

The simulated active network is currently a computed cell-mask and metric
layer. HydroModPy does not yet automatically persist a canonical vector feature
named ``hydrographic_network_simulated_active``.

That distinction is deliberate.

Before vectorization becomes a stable contract, the project still needs to
choose:

- the default activation threshold;
- whether the canonical representation is one steady network, one transient
  summary, or several named networks;
- how much simplification or line extraction should be applied;
- whether the first canonical representation should be raster-like, vector-like,
  or both.

Until those choices are fixed, the safest interpretation is:

- use ``outflow_drain`` for local drainage outflow and budget reasoning;
- use ``accumulation_flux`` for active-branch detection;
- use ``simulated_active_network`` figures and overlap metrics for inspection;
- do not assume that a stored vector hydrographic-network role exists.

Related Reading
---------------

- :doc:`../streams_and_seepage/index`
- :doc:`../streams_and_seepage/conceptual-model`
- :doc:`../streams_and_seepage/status-and-limitations`
- :doc:`stream-ocean-and-drainage-semantics`
- :doc:`../solvers/flow/modflow/modflow6`
- :doc:`../../architecture/overview/hydrographic-network-simulated-active-inventory`
- :doc:`../../getting_started/comparison-workflow`

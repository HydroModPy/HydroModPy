Hydrographic Network Simulated-Active Inventory
===============================================

Purpose
-------

This page records what HydroModPy already exposes for the hydrographic network
that emerges from simulated flow fields, and what is still missing before that
output can become one first-class canonical role:

- ``HydrographicNetwork(role="simulated_active")``

It is intentionally different from the existing ``reference`` and
``generated`` roles.

- ``reference`` is loaded from external hydrography data.
- ``generated`` is derived from the DEM and persisted as one geographic
  network feature.
- ``simulated_active`` would come from time-varying simulated drainage or
  stream activity fields.

Current Contract Status
-----------------------

The canonical role already exists in the type contract:

- ``HydrographicNetworkRole = "reference" | "generated" | "mesh_constraint" | "simulated_active"``
- ``HydrographicNetworks`` already has one optional ``simulated_active`` slot.
- ``Run.available_hydrographic_network_roles()`` already knows about that role.

What is missing today is not the name, and not the cell-field population path,
but the final canonical vector population path:

- no workflow step currently writes a persisted
  ``hydrographic_network_simulated_active`` geographic feature,
- no vectorization contract currently decides which timestep, threshold or
  aggregation window should define that role,
- no display figure currently treats the simulated-active network as a stored
  canonical line network.

The computed cell-field path is implemented. HydroModPy can store positive
``outflow_drain``, route it to ``accumulation_flux``, expose computed active
masks, and render active-network cell-map figures when the run carries a
plottable mesh.

HydroModPy does now expose a conservative computed API layer:

- ``run.simulated_active_network_mask()``
- ``run.simulated_active_network_metrics()``
- ``run.simulated_active_network_overlap_metrics()``
- ``run.simulated_active_network_distance_metrics()``
- the ``simulated_active_network`` display figure
- the ``simulated_active_network_reference_overlay`` validation figure

These APIs compute cell masks, persistence maps, and scalar metrics from the
persisted ``accumulation_flux`` field without declaring that a canonical vector
feature exists.

Steady, Persistent, Always Active
---------------------------------

The terminology must stay explicit because three related ideas are easy to
confuse:

- ``steady`` describes the model regime or scenario used for a representative
  steady-state flow computation.
- ``persistent`` describes a transient occupancy rule: a cell is active for at
  least a chosen fraction of timesteps, for example 50% or 80%.
- ``always_active`` describes a stricter transient occupancy rule: a cell is
  active at every stored timestep of the analysed window.

New code and documentation should use ``steady`` for the representative
steady-flow concept. A simulated steady active network should preferably be
defined from a representative ``flow_regime = "steady"`` run, then compared to
``reference`` with ``run.simulated_active_network_overlap_metrics(...)`` or
visualized with ``simulated_active_network_reference_overlay``.

The computed API is now regime-aware when no ``mode`` is provided:

- ``flow_regime = "steady"`` resolves to the steady-state active field,
  implemented on the persisted timestep API as ``last``.
- ``flow_regime = "transient"`` resolves to ``persistent`` for transient
  diagnostics.
- an explicit ``mode`` still overrides the default and should be used for
  transient diagnostics.

This avoids making a one-year transient chronicle, its spin-up, or an arbitrary
drought period define the representative steady active network.

What Already Exists In The Simulation Outputs
---------------------------------------------

Several outputs already describe the active drainage or stream behavior of a
simulation.

Derived fields persisted in the simulation catalog
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The main ingredients are in
``hydromodpy/simulation/extraction/extractors/derived.py``:

- ``outflow_drain`` is positive drain outflow per cell, summed over model
  layers, stored under ``derived/outflow_drain``, and computed per timestep.
  It is normalized from raw MODFLOW budget signs where groundwater outflow may
  be stored as a negative cell-budget contribution.
- ``accumulation_flux`` is the downstream accumulation of positive drain
  outflow, stored under ``derived/accumulation_flux`` and computed per
  timestep. It uses structured D8 support when a regular raster route is
  available, mesh face connectivity for MODFLOW 6 / DISV-style supports when
  topology is present, and local positive ``outflow_drain`` as a conservative
  fallback when routing is unavailable.

Those fields are persisted as cell arrays in the Zarr run store, not as
geographic vector features.

MODFLOW 6 mesh support
^^^^^^^^^^^^^^^^^^^^^^

The MODFLOW 6 output adapter now writes enough mesh topology for the active
network view to be displayed on the solver support:

- ``mesh/vertices``,
- ``mesh/face_node_connectivity``,
- ``mesh/surface_top``,
- ``mesh/z_interfaces``,
- ``mesh.attrs["structured_shape"]`` when a regular 2D solver shape can be
  inferred.

This matters when the MODFLOW 6 solver grid is not the same shape as the
geographic DEM grid. In that case ``Run.fields("accumulation_flux")`` uses the
solver-grid shape when it is known, instead of forcing a DEM reshape.

Lazy result views already built on top of those fields
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

``hydromodpy/results/views.py`` already exposes catchment-scale summaries:

- ``run.drainage_density()``: fraction of active catchment cells with positive
  ``accumulation_flux``; useful as one occupancy metric of the active stream
  network.
- ``run.persistence(variable="accumulation_flux")``: per-cell fraction of
  timesteps above a threshold; useful for transient persistent/intermittent
  behavior.
- ``run.simulated_active_network_mask()``: per-cell active-network view with a
  regime-aware default and optional explicit modes:

  - ``last`` for one timestep snapshot,
  - ``any`` for cells active at least once,
  - ``persistent`` for cells active above a declared persistence threshold,
  - ``always_active`` for cells active at every timestep of the analysed
    transient window,
  - ``persistence`` for the continuous active-time fraction.

- ``run.simulated_active_network_metrics()``: scalar occupancy summary over the
  same active field.
- ``run.simulated_active_network_overlap_metrics()``: cell-overlap diagnostic
  between the simulated active cells and the observed ``reference`` vector
  network.

``hydromodpy/analysis/stream_networks/metrics.py`` now exposes a comparison
analysis that combines the active mask, mesh geometry, and the persisted
``reference`` network:

- ``run.simulated_active_network_distance_metrics()``: planar bidirectional
  cell-centroid distances between active simulated cells and the selected
  vector role, usually ``reference``.

Those views are already scientifically meaningful, but they remain scalar or
raster-like summaries, not one canonical stored network object.

Display support already present
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The display registry now includes:

- ``simulated_active_network``
- ``simulated_active_network_reference_overlay``

The first figure renders the computed cell mask over the simulation mesh when
``accumulation_flux`` and a plottable mesh are present. The second overlays
that simulated active mask with the observed ``reference`` linework and displays
coverage / precision / F1 / Jaccard metrics in the figure. Both are deliberately
cell-map views. They are not a stored ``hydrographic_network_simulated_active``
line feature and should not be interpreted as a vectorized river network.

Comparison workflow support already present
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The comparison stack already knows a lot about those simulated flux outputs:

- ``hydromodpy/analysis/comparison/runtime.py`` supports observables based on
  ``accumulation_flux`` and ``outflow_drain``.
- ``hydromodpy/analysis/comparison/visuals.py`` already produces maps and
  other figures for those fields.
- example scripts such as
  ``examples/projects/02_nancon_watershed/run_transient_prototype.py`` already
  use:

  - ``run.fields("accumulation_flux")``
  - ``run.fields("outflow_drain")``
  - ``run.drainage_density()``

This means the scientific signal is already present. What is still absent is a
shared hydrographic-network storage contract.

The comparison workflow can also write:

- ``simulated_active_network_metrics.csv``
- ``simulated_active_network_metrics_skipped.json``
- ``simulated_active_network_overlap_metrics.csv``
- ``simulated_active_network_overlap_metrics_skipped.json``
- ``simulated_active_network_distance_metrics.csv``
- ``simulated_active_network_distance_metrics_skipped.json``

The metrics export summarizes active-network occupancy signatures between
variants. The overlap export compares the simulated active cells with the
observed ``reference`` network by rasterizing that vector network onto the mesh.
The distance export adds bidirectional planar cell-centroid distances. These
exports are intentionally separate from ``hydrographic_network_metrics.csv``,
which compares persisted vector linework roles.

There is also a Run-level overlap diagnostic:

- ``run.simulated_active_network_overlap_metrics(network_role="reference")``
- ``run.simulated_active_network_distance_metrics(network_role="reference")``

This does not vectorize the simulated network. It rasterizes the selected
persisted vector role onto mesh cells by intersection, then compares that cell
occupancy with the computed simulated-active mask and can also summarize
planar distances. This is the right intermediate comparison before committing
to a canonical vectorization rule. The scientific validation comparison is
against ``reference``. If ``reference`` is missing, the comparison should be
skipped. HydroModPy should not silently fall back to ``generated`` because that
would replace an observation-vs-model question with a topography-vs-model
diagnostic.

What Does Not Yet Exist
-----------------------

HydroModPy does not yet provide the following for the simulated-active vector
network:

- no persisted canonical geographic feature named
  ``hydrographic_network_simulated_active``,
- no vector shapefile or GeoDataFrame contract built automatically from
  ``accumulation_flux``,
- no stable vectorization contract for choosing one timestep or one aggregation
  window,
- no explicit distinction yet between:

  - instantaneous active network,
  - seasonal or event-specific active network,
  - persistent transient active network,
  - steady active network.

This is the main reason why the role exists in the class contract but stays
empty in practice.

Storage And Representation Options
----------------------------------

The main design choice is not "should HydroModPy store simulated activity?",
but "which representation should become canonical?".

Option A - Keep raw fields only
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Keep ``accumulation_flux`` and ``outflow_drain`` as raw persisted fields and do
not introduce one stored hydrographic network feature.

Pros:

- minimal change,
- no ambiguity about thresholds,
- naturally keeps the time dimension.

Cons:

- cannot compare with observed ``reference`` using the same
  hydrographic-network API,
- makes figures and metrics remain ad hoc and field-specific.

Option B - Add one raster-like canonical active network
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Persist one thresholded 2D mask derived from ``accumulation_flux`` or from a
time-aggregated persistence field.

Pros:

- easy overlap metrics against other raster masks,
- simpler than full vectorization,
- keeps a close link with the raw cell fields.

Cons:

- still not one true line network,
- comparison with the vector ``reference`` network remains indirect.

Current status:

- a non-persisted computed version now exists via
  ``run.simulated_active_network_mask()`` and the
  ``simulated_active_network`` figure;
- the persisted canonical-mask contract is still undecided.

Option C - Add one vectorized canonical active network
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Threshold and vectorize one selected simulated-active representation, then
persist it as ``hydrographic_network_simulated_active``.

Pros:

- aligns well with the existing canonical network comparison API,
- allows length-based metrics and geometry diff views,
- makes the three roles structurally comparable.

Cons:

- requires explicit threshold and time-window rules,
- vectorization quality may vary strongly with mesh type and routing quality.

Recommended Direction
---------------------

The cleanest next step is a staged approach:

1. Keep the raw per-timestep fields exactly as they are.
2. Use the documented computed mask API for development and visual inspection.
3. Decide whether to persist one canonical mask, one vectorized network, or
   both.
4. Only then derive one canonical persisted hydrographic network role from
   that aggregated mask.

The first aggregation contract should stay simple and deterministic. Two good
starting candidates are:

- one thresholded snapshot at a declared timestep or season,
- one persistence-based mask over the full simulation or one declared year,
- one steady scenario with representative recharge.

The implementation should also leave room for several named simulated-active
representations instead of forcing one global answer too early. A project may
need, for example, one ``steady`` network plus one or more transient
``persistent`` variants.

That would avoid mixing two questions:

- "what did the solver simulate at each timestep?"
- "which one network representation should HydroModPy compare with the
  loaded and DEM-derived networks?"

Metrics Already Available Or Easy To Add
----------------------------------------

Already available without changing storage:

- drainage density timeseries,
- persistence maps,
- ``run.simulated_active_network_mask()`` for cell-level active-network views,
- ``run.simulated_active_network_metrics()`` scalar occupancy metrics,
- ``run.simulated_active_network_overlap_metrics()`` against an existing
  vector role,
- ``simulated_active_network`` display figure,
- ``simulated_active_network_reference_overlay`` validation figure,
- comparison export ``simulated_active_network_metrics.csv``,
- outlet flux and drainage-field comparisons through the comparison workflow,
- active-cell fraction and activity timing.

Natural next metrics after a canonical active-network representation exists:

- active-network total length,
- overlap with ``reference``,
- missing and extra active branches,
- precision / recall / F1 on raster occupancy,
- Hausdorff-like distance for vectorized active lines,
- seasonal persistence classes such as persistent vs intermittent branches,
  separate from the steady active-network concept.

Open Design Questions
---------------------

Before implementing the role, a few questions need one explicit answer:

1. What should define the canonical time window?
2. What threshold should turn ``accumulation_flux`` into active linework?
3. Should the first comparison be raster-based, vector-based, or both?
4. How should the contract behave on unstructured meshes when routing support
   differs from structured cases?
5. Should ``simulated_active`` represent one canonical network, or a named set
   of networks such as ``steady``, ``transient_persistent_50`` and
   ``event_snapshot``?

Until those questions are fixed, the safest position is:

- keep the role declared in the class model,
- keep the raw simulated fields persisted and comparable,
- expose computed masks and maps for development,
- do not yet auto-populate ``hydrographic_network_simulated_active``.

Related reading
---------------

- :doc:`../../theory/hydrology/simulated-active-network`
- :doc:`mental-model-and-design-choices`
- :doc:`hydrographic-network-uml-diagrams`
- :doc:`../../user_guide/concepts/comparison-workflow`

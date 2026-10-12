Simulated active network
========================

What HydroModPy computes for the network that emerges from simulated flow, and what it
does not store. The simulated active network is a view of a run. It is not a stored
vector network.

Three networks, three roles
---------------------------

- ``reference`` is loaded from external hydrography data.
- ``generated`` is derived from the DEM and persisted as one geographic feature.
- ``simulated_active`` would come from simulated drainage or stream-activity fields.

The role exists in the type contract (``HydrographicNetworkRole`` and the
``HydrographicNetworks.simulated_active`` slot of
``hydromodpy/spatial/geographic/core/hydrographic_network.py``), and
``Run.available_hydrographic_network_roles()`` knows its name. No workflow step writes a
``hydrographic_network_simulated_active`` geographic feature, so the slot stays empty in
practice.

What a run offers instead
-------------------------

The run stores the per-cell budget terms (``budget/``), and two cell fields are rebuilt from them
on read (:mod:`hydromodpy.results.derive.virtual_fields`):

- ``outflow_drain`` is the positive drain outflow of each cell, summed over layers and
  normalised from the raw MODFLOW budget signs;
- ``accumulation_flux`` is the downstream accumulation of that outflow. It is routed on the
  stored descent D of the mesh (:doc:`../solver/backends`). Boussinesq stores D once per run
  for a raster run, built from the Whitebox D8 pointer of its filled top, because its store
  holds a top and no mesh connectivity.

Both are cell fields of the run. The MODFLOW 6 output adapter also writes the
mesh topology the views need (``mesh/vertices``, ``mesh/face_node_connectivity``,
``mesh/topography``, ``mesh/z_interfaces``), so a field keeps the shape of the solver
grid when it differs from the DEM grid.

Lazy views of the run
---------------------

``hydromodpy/results/derive/views.py`` computes these from the fields of the run (stored or rebuilt on read), without
changing the catalog:

``run.drainage_density()``
   The fraction of active catchment cells with a positive ``accumulation_flux``.

``run.persistence(variable="accumulation_flux")``
   The fraction of timesteps above a threshold, per cell.

``run.cell_field_active_mask()``
   The per-cell active network. The mode is ``last`` (one timestep), ``any``,
   ``persistent`` (active above a declared fraction), ``always_active`` (active at
   every timestep of the window) or ``persistence`` (the continuous fraction). Without
   a mode, ``flow_regime = "steady"`` reads the steady state and ``"transient"`` reads
   ``persistent``.

``run.cell_field_active_metrics()``
   Scalar occupancy of the same field.

``run.cell_field_network_overlap_metrics(network_role="reference")``
   The overlap between the active cells and a stored vector network, which is
   rasterised onto the mesh cells by intersection (coverage, precision, F1, Jaccard).

``run.cell_field_network_distance_metrics(network_role="reference")``
   The planar distances between the centroids of the active cells and that network, in
   both directions.

The figures ``simulated_active_network`` and ``simulated_active_network_reference_overlay``
draw the mask and its overlay with the reference. Both are cell maps, not a vectorised
river network. They need ``accumulation_flux`` and a plottable mesh.

The comparison workflow writes the matching exports: the metrics, the overlap and the
distance, each with a ``..._skipped.json`` that says why a simulation was left out
(:doc:`../simulation/comparison-workflow`).

Words to keep apart
-------------------

- ``steady`` is a flow regime: a representative steady-state computation.
- ``persistent`` is an occupancy rule: a cell active during at least a chosen fraction of
  the timesteps.
- ``always_active`` is the strict rule: a cell active at every stored timestep of the
  window. ``perennial`` is a legacy alias of it in the computed API.

A steady active network should come from a representative ``flow_regime = "steady"`` run
and be compared with ``reference``. A one-year transient chronicle, its spin-up or a
drought period must not define the representative steady network.

The comparison target
---------------------

The validation question is "does the simulation reproduce the observed network?", so the
target is ``reference``. When ``reference`` is missing, the comparison is skipped.
HydroModPy does not fall back to ``generated``: that would replace a question about the
observation with a question about the topography.

What is not stored
------------------

There is no persisted ``hydrographic_network_simulated_active`` feature, no vector file
built from ``accumulation_flux``, and no rule that picks one timestep or one aggregation
window for such a network. The raw fields keep the time axis, and the views above answer
the questions that do not need one stored network.

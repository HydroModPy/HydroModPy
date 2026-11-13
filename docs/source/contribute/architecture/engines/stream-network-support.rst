Supports and the simulated network
==================================

This note covers two things a heterogeneous model needs. The first is the zone supports that a
parameter maps onto, which are declared in ``[domain.supports]``. The second is the networks that
hydrography gives, and the views of a run that read the network the simulated flow draws. The
modules are listed on :doc:`../packages/model` and :doc:`../packages/catchment`.

How a support is chosen
-----------------------

A support is a set of zones with labels. A heterogeneous ``FieldParam`` points to one by
``field_spatial_id``, and its ``values`` use the labels as keys. A homogeneous parameter needs no
support. The keys of a heterogeneous parameter are listed in :doc:`/reference/parameters/flow/param`,
the supports in :doc:`/reference/parameters/domain`, and ``value__delete`` in
:doc:`/reference/parameters/grammar`.

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - ``kind``
     - Use it when
   * - ``geology``
     - The zones come from the geology dataset that the data step loads. It is never inferred, so
       the file declares it.
   * - ``generated_bands``
     - One axis cuts the domain at a few break coordinates, for layered strips and for 2D tests
       that are still 1D.
   * - ``generated_rings``
     - The zones are distances to a centre, for radial or concentric cases.
   * - ``catchment_zones``
     - The zones already exist as a partition of the catchment, and the model reuses them.

A file may mix kinds in one :toml:`domain.supports` mapping. The support id must equal the
``field_spatial_id`` and the value keys must equal the labels. A bands support looks like this.

.. code-block:: toml

   [domain.supports.k_x]
   kind = "generated_bands"
   axis = "x"
   coordinate_mode = "absolute"
   breaks = [200.0, 500.0]
   labels = ["left", "middle", "right"]

   [flow.param.K.field]
   kind = "heterogeneous"
   value__delete = true
   unit = "m/s"
   field_spatial_id = "k_x"
   values = { left = 1.0e-4, middle = 5.0e-5, right = 1.0e-5 }

Support code
------------

The typed declarations are in ``hydromodpy/model/domain/spatial_support_config.py``. Each kind has
a provider in ``spatial_support.py``, found through ``SpatialSupportProviderRegistry``, and the
providers use ``support_fields.py`` for the band, ring and raster zones.

A provider declares a ``build_phase``. The bands, rings and catchment zones are built at
``setup``. The geology support is built at ``data``, because it needs the loaded geology.
``build_phase_supports`` builds the supports of one phase and leaves alone a support the domain
already holds under its id. ``validate_domain_support_contract`` fails early when a heterogeneous
parameter names a support that the file does not declare.

On the consumer side, ``hydromodpy/model/properties/zone_fractions.py`` gives the fraction of
every zone in every cell, for every mesh. ``property_table.py`` is the one mapping of a
heterogeneous parameter to solver arrays.

Common mistakes
---------------

- A ``field_spatial_id`` without a support under the same id. The check above refuses it.
- A geology support left out because the file expects it to appear. It must be declared.
- ``generated_bands`` for a radial case, or ``generated_rings`` for a zoning that really comes
  from catchment data.

Three networks, three roles
---------------------------

``HydrographicNetworkRole`` in ``hydromodpy/catchment/algorithms/hydrographic_network.py`` names
the networks of a project. ``reference`` is loaded from external hydrography data. ``generated``
is derived from the DEM and stored as one geographic feature. ``simulated_active`` would come from
simulated drainage fields. The slot exists in the type contract, and
``Run.available_hydrographic_network_roles()`` knows its name. No workflow step writes a
``hydrographic_network_simulated_active`` feature, so the slot stays empty. The simulated active
network is a view of a run and not a stored vector network. The theory is in
:doc:`/theory/exits/simulated-network`.

What a run offers
-----------------

The run stores the per-cell budget terms in ``budget/``. Two cell fields are rebuilt from them on
read in ``hydromodpy/results/derive/virtual_fields.py``. ``outflow_drain`` is the positive drain
outflow of each cell, summed over layers and normalized from the raw MODFLOW budget signs.
``drain_accumulation_flux`` is the downstream accumulation of that outflow, routed on the stored
descent D of the mesh (:doc:`backends`). A Boussinesq run stores no D, so ``Run.catchment_mask`` falls back to the DEM raster for it. The MODFLOW 6 output adapter also writes the mesh topology that the views need, so
a field keeps the shape of the solver grid when it differs from the DEM grid.

The lazy views are functions of ``hydromodpy/results/derive/views.py`` and methods of the run.
They change nothing in the catalog.

- ``drainage_density`` is the fraction of active cells of the catchment with a positive
  ``drain_accumulation_flux``.
- ``persistence`` is the fraction of timesteps above a threshold, per cell.
- ``cell_field_active_mask`` is the per-cell network, in one mode among ``last``, ``any``,
  ``persistent``, ``always_active`` and ``persistence``. Without a mode, ``flow_regime =
  "steady"`` reads the steady state and ``"transient"`` reads ``persistent``.
- ``cell_field_active_metrics`` is the scalar occupancy of that field.
- ``cell_field_network_overlap_metrics`` and ``cell_field_network_distance_metrics`` compare the
  active cells with a stored vector network, by overlap (coverage, precision, F1, Jaccard) and by
  planar distance between centroids, in both directions.

The support of a view follows its name. The drainage density, the active metrics and the two
comparison metrics read the active cells of the basin of D (``mesh/descent_basin``), taken in
whole cells, and ``catchment_cell_count`` counts them. A run that stores no such basin, or only
the largest basin of a synthetic domain, reads the active domain instead and logs it.
``cell_field_active_mask`` and the maps keep the active domain, which is the cells whose model top
is finite. ``catchment_mean`` and ``budget_over`` weigh each face by its area inside the
catchment polygon (:doc:`/theory/mesh`).

The variable ``simulated_active_network`` draws the mask, and ``overlays = ["relief", "network"]``
adds the mapped network over it. The figure is a cell map and needs ``drain_accumulation_flux`` and
a plottable mesh. A comparison writes the overlap and the distance of each run in ``network.csv``
(:doc:`toml-to-solver`).

Words and rules to keep
-----------------------

``steady`` is a flow regime. ``persistent`` is an occupancy rule, a cell active for at least a
chosen fraction of the timesteps. ``always_active`` is the strict rule, a cell active at every
stored timestep of the window, and ``perennial`` is a legacy alias of it in the computed API.

A steady network comes from a representative ``flow_regime = "steady"`` run. A one-year
transient chronicle, its spin-up or a drought period must not define it.

The comparison target is ``reference``, because the question is whether the simulation
reproduces the observed network. When ``reference`` is missing, the comparison is skipped.
HydroModPy never falls back to ``generated``, which would replace a question about the
observation with a question about the topography.

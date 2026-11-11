Package: model
==============

.. include:: ../../../../../hydromodpy/model/README.md
   :parser: myst_parser.sphinx_
   :start-line: 1

Modules
-------

.. hmp-module-table:: model

Inside the package
------------------

The folders
~~~~~~~~~~~

Each folder answers one question. ``domain/`` says where the aquifer lies. It holds the
``Domain``, its depth models and layers, the supports a parameter can be zoned by, the lake bed
and the ``domain-build`` worker. ``properties/`` says what value a parameter takes in each cell.
It holds ``FieldParam``, the zones, the depth profile, the geology field and
``property_table.py``, which maps K, Sy and Ss onto the cells for every solver. ``forcing/`` says
how a series or a grid becomes the rate a solver reads. ``boundaries/`` holds the boundary ids and
the binders that put loaded data on a built ``Flow``, and it is a port with its own README.
``sinks_sources/`` holds one payload per sink or source of ``[flow.sinks_sources]``. ``initial/``
holds the head a run starts from, in numpy. ``time/`` holds the flow regime and the time axes of
transient histories. ``soil/`` holds the arithmetic of the daily soil reservoir. ``transport/``
holds ``TransportConfig``, the ``[transport]`` table. At the root, ``contracts.py`` gives the two
protocols through which the model reads loaded data, ``flow_config.py`` and ``initial_config.py``
hold the ``[flow]`` schema and the ``[flow.ic]`` and ``[spinup]`` payloads, ``payloads.py`` holds
the generic initial-condition, boundary-condition and sink models, ``supports.py`` holds the
closed set of names a solver backend lists in ``supports``, and ``flow.py`` and ``model.py`` hold
the two runtime objects.

How a flow is built
~~~~~~~~~~~~~~~~~~~

A flow is built in five steps. ``HydroModPyConfig.from_toml`` hands the ``[flow]`` table to
``FlowConfig.from_toml_section`` in ``flow_config.py``. It canonicalizes the boundary ids,
resolves the forcing paths and validates the table into a ``FlowConfig``. Then
``Flow(config=cfg.flow)`` runs ``set_config``. It fills ``parameters`` (``FieldParam`` objects),
``initial_conditions``, ``boundary_conditions`` and ``sinks_sources``, and it converts the well
fluxes and the recharge to SI. ``ensure_flow`` in ``workflow/steps/data.py`` builds it at setup.

After the data step, ``workflow/steps/data.py`` calls the ``apply_*_to_flow`` functions of
``boundaries/``. They put the sea level, the recharge and the ETP (``climate.py``), the lakes
(``lakes.py``), the SFR reaches and the runoff they route (``streams.py``) and the barriers
(``barriers.py``) on the ``Flow``. The same cascade runs for a calibration trial.

Then ``prepare_solver`` calls ``model_from_flow`` and gets a ``Model``. It holds the same objects
as the ``Flow``, in SI, with the geometry, the time grid and the shared solver options beside
them. A prior run is read into a ``PriorState`` there, so no adapter opens a Zarr store. The river
network A is also read on the cells there (``Geometry.channel_exits``, ``None`` for a run without
A), so no adapter projects A itself.

A solver adapter reads the ``Model`` and never the ``Flow``. It resolves each dated forcing to one
value per stress period with ``forcing/time_forcing.resolve_period_values_from_forcing``. A
spatialized source gives its series at the step of the source in ``Model.native_recharge``
(``forcing/native.py``), read by area on a one-cell mesh. The boundary support of each backend
comes from ``FLOW_BOUNDARY_DEFINITIONS``. A change to the model is a new object, made by
``with_properties``, ``with_initial``, ``steady_variant`` or ``cycle_variant``, and the ``Model``
of the run stays as it was.

The domain
~~~~~~~~~~

The domain is the aquifer as a body of rock. It takes the ground surface from the DEM, puts the
base of the aquifer below it with a depth model, and cuts the column between the two into layers.
The mesh decides the cells in the plan, and this folder decides what is above and below each cell.
The ``[domain]`` table is read into a ``DomainConfig`` with three parts, the depth model, the
layers and the supports. ``build.py`` builds a ``Domain`` from that config and a surface, and it
is the one constructor of a domain geometry. The setup step, the rebuild of a live project, the
domain case and the ``domain-build`` capability all call it.

There are four depth models, each with its own ``kind`` in ``depth_model_config.py``. They are
``constant_thickness``, ``flat_substratum``, ``raster_substratum`` and ``raster_thickness``. The
first two need no file. The two raster models read a raster from ``[data.substratum]``, and
``build.py`` reads it (``read_substratum_source``). A layering by surfaces can also read one base
raster per layer (``read_layer_base_sources``). ``layering.py`` turns ``[domain.layers]`` and the
two surfaces into the bottom and the ``idomain`` of every layer. It works on arrays only, so it
knows no ``Domain``, and the solvers read its result.

Once the data is loaded, ``structure_binders.py`` writes the geology and the catchment zones into
the domain. The catchment zones are a ``CatchmentZonesField``, defined in
``catchment/algorithms/catchment_zones_field.py`` beside the code that computes them. A
heterogeneous parameter asks for a support. A provider in ``spatial_support.py`` builds a support
field (``support_fields.py``), which gives the zone share of each cell of a mesh. The bands, rings
and catchment zones that a project uses are built here, and ``properties/`` holds the base class
they derive from.

The lake bed rebuilt from a bathymetry raster lives here too, because it changes the top and the
layers of the cells under a lake. ``lake_bed_regrid.py`` gives each lake cell the mean of the
bathymetry pixels in it, and ``lake_bed_abacus.py`` remaps the elevations by area-weighted
quantiles so the lake fills the way its abacus says. The solver then re-grades each column of
layers around the carved bed, in ``solver/modflow6/builders/lake_column_regrade.py``.

The ``domain-build`` capability does the first two steps as a job. A request names a DEM and a
depth model. The worker calls the same ``build_domain``, writes the rasters of the top and the
base, and seals a ``domain.json`` for the mesh generator. It is a capability for outside tools. No
``hmp`` command and no step of a run starts it. A tool stages a job directory, whose contract is
in ``hydromodpy/schema/job/``, and calls ``worker.run(job, exit_code_for=...)``. Only the tests in
``tests/integration/domain/`` call it inside this repository. It stays on purpose, so keep it when
you tidy the package.

Properties
~~~~~~~~~~

A parameter is one number for the whole domain, or one number per zone (geology class, band,
ring), and it can fall with depth. A ``FieldParam`` (``field_param.py``) holds the values of one
parameter in SI units and its depth profile if it has one. ``field_param_io.py`` reads it from a
TOML file or a mapping, and ``core/config_kit/field_param/config.py`` checks it. The TOML sections
of a field parameter live in ``core/config_kit/field_param/``, because ``model/flow_config.py``
reads them too.

A ``Field`` (``field_spatial.py``) is a zone map. Its ``on_mesh`` method cuts a mesh into zones
and returns, for each zone, the share of every cell. The shares come from sample points in each
cell (``cell_sampling.py``) or from the polygons of the zones (``zone_fractions.py``).
``FieldParam.to_mesh_field`` weights the zone values with the shares, applies the depth factor of
``vertical_profile.py`` and returns a ``MeshWithValues`` (``mesh_cells.py``), the mesh with one
value per cell.

``property_table.map_flow_properties`` does this for K, Kv, Sy, Ss and the K tensor of a flow, per
layer for MODFLOW and once for Boussinesq, and it refuses a conductivity or a storage that is not
positive. ``resolve_flow_property_runtime_overrides`` applies the values a calibration trial
writes, and ``resolve_required_flow_properties`` lists the properties a regime needs.
``property_ids.py`` holds the one table of the ids of ``[flow.param.<id>]``. The geology field
``GeologyField`` and ``FieldSquare`` live here as well. The geology data is loaded in
``data/variables/geology/``, and ``field.py`` there builds a ``GeologyField`` from it. A
``GeologyField`` built alone from a config mapping or a TOML section comes from ``io.py`` in the
same folder (``geology_field_from_config`` and ``geology_field_from_toml``). The unit-square
meshes of ``unit_square_mesh.py`` and the two-zone field serve the field demos of
``tools/cases/field/`` and the tests.

Forcing
~~~~~~~

A forcing is a rate that changes in space and in time, such as recharge or precipitation. It comes
as a series, as a grid (a NetCDF or GeoTIFF file, or an xarray dataset) or as time series at
stations. The folder aligns a series to the stress periods, and it puts a grid or stations on the
cells of a mesh as one rate per cell and per stress period, in m/s. Every solver takes this one
path, whatever the mesh engine, so a regular grid, a triangulation and a Voronoi mesh are served
alike.

A solver builder or the workflow calls ``discretize_fields_on_cells`` or
``discretize_points_on_cells`` in ``cells.py``, with the loaded records, the cell centers, the
number of stress periods, the simulation window and the interpolation method. ``cells.py`` turns
the window into the bounds of each stress period (``stress_period_bounds``). For a grid,
``rasters.py`` reads each record. A record whose CRS is not the CRS of the mesh is refused,
because a grid is never reprojected. A dataset or a NetCDF file is averaged in time over each
period. A GeoTIFF gives one band per time step, and a rotated GeoTIFF is refused. For stations,
``stations.py`` refuses a station whose location is in another CRS than the mesh, then takes the
mean of each series over each period. The coverage rule of ``core/time/coverage.py`` says which
samples a period takes and what happens when the record does not reach it.

``sources.py`` refuses a nodata pixel under a cell, then interpolates onto the cells. The methods
are ``nearest``, ``linear`` and ``idw`` (``interpolation.py``), and ``area``
(``area_weights.py``). The area method weighs each pixel by the area it shares with the cell
polygon, so a cell rate times the cell area is the integral of the grid over the cell. It needs
the planar mesh and is refused for stations. The values are multiplied by the unit factor of the
record, so they come out in m/s. When several records cover one period, the period takes their
mean with equal weights. A cell reads valid pixels only, and a refusal says which cell and which
period. The folder also gives the spatial mean of a grid (``spatial_mean_from_fields``), the
homogeneous series used when a forcing is not spatial.

A series that does not go through a mesh follows another path. ``forcing_bridge.resolve_forcing``
turns a loaded record into the series the flow keeps. ``time_alignment.py`` gives it one value per
stress period of ``[simulation.time]``, each monthly or yearly sample weighed by its length.
``steady_periods.py`` is the rule every solver shares for a steady period, and ``time_forcing.py``
resolves a dated forcing to one value per period. ``recharge_rates.py`` gives the mean recharge
that the stream-network criterion divides by. ``solver``, ``results`` and ``calibration`` read it,
so the trials that score a run and the figures that redraw it use one mean recharge. A period
before the first sample has no data, so ``forcing_period_rates`` gives it NaN and
``criterion_mean_recharge`` gives it no weight.

The soil reservoir
~~~~~~~~~~~~~~~~~~

The daily soil reservoir makes a recharge from the weather before the groundwater solve.
``soil/kernel.py`` holds the arithmetic, one function per equation with its reference. It needs
only numpy and follows rule 6, so it reads from top to bottom and imports no neighbour. The rest
sits in ``forcing/``, because it reads the records that a project loads. ``soil_config.py`` is
what ``[flow.sinks_sources.recharge.soil]`` can say, with each bound and its refusal in two
tables. ``soil_grids.py`` reads the precipitation and ETP grids on the days of the run and checks
them: daily step, calendar, CRS, no gap, no negative value and a plausible scale. It never touches
the cached dataset of a shared record. ``soil_columns.py`` places one column per SAFRAN cell, or
one per capacity class inside each cell when ``[data.soil_capacity]`` gives a raster, each weighed
by its share of the catchment. ``soil_forcing.py`` runs the kernel day by day
(``compute_soil_forcings``) and hands back the recharge, the residual ETP and the runoff on the
precipitation grid. ``ru_ladder`` gives the basin recharge for a few soil capacities, and
``soil_budget.py`` writes the water-budget block of the run. These modules read the loaded records
through ``model/contracts.py``, so nothing here imports ``data``. The recharge binder of every run
reads the section, and the soil applies to MODFLOW 6 only. The PyHELP recharge model is not here.
It sits in ``hydromodpy_annex/physics/pyhelp/`` and runs from a checkout.

Sinks and sources
~~~~~~~~~~~~~~~~~

``sinks_sources/container.py`` holds ``FlowSinksSourcesConfig``, the whole
``[flow.sinks_sources]`` table, and ``Flow.set_sinks_sources`` reads it. Each other module holds
the payload of one kind. ``recharge.py`` and ``etp.py`` carry a steady first period
(``first_clim``), normalized by ``forcing/steady_periods.py``. ``wells.py`` also holds the report
of a well whose pumping MODFLOW 6 cut. ``lake.py`` holds a lake, its outlets and its forcings,
with the sign each forcing must have. ``flow_barrier.py`` holds a flow barrier and
``CutoffWallConfig``, the barrier of a lake dam laid on the shore.

Rules between the modules
~~~~~~~~~~~~~~~~~~~~~~~~~

``tests/unit/architecture/layer_matrix.yaml`` gives the model ``core``, ``schema``, ``catchment``,
``mesh`` and itself. The model never imports ``data``, ``results`` or ``solver``. It sees loaded
data through the ``LoadResultProto`` and ``FieldRecordProto`` of ``contracts.py``, and it builds
its field parameters with the ``FieldParam`` of ``properties/field_param.py``.

Inside the package, ``boundaries/`` reads ``contracts``, ``forcing``, ``payloads`` and
``sinks_sources``, and it reads ``flow.py`` for annotations only. ``sinks_sources/`` reads
``forcing``. ``forcing/`` reads ``contracts``, and the ``soil_*.py`` modules read
``soil/kernel.py``. ``flow.py`` reads ``payloads``. ``domain/`` reads ``properties/`` and
``properties/`` reads ``time/``. ``flow_config.py``, ``flow.py``, ``initial_config.py`` and
``model.py`` read the folders. The only cycle is the annotation of ``Flow`` in ``boundaries/``,
which stays under ``TYPE_CHECKING``. ``soil/`` and ``initial/`` follow rule 6. A module there
imports the standard library, numpy and at most one neighbour of its folder, and
``tests/unit/architecture/test_science_module_imports.py`` holds it.

Inside ``domain/``, ``depth_model_config.py``, ``layers_config.py`` and
``spatial_support_config.py`` import only ``core``, and ``domain_config.py`` reads these three.
``layering.py`` reads ``layers_config.py`` and ``core``. ``build.py`` and ``domain.py`` read the
config modules, ``catchment/surface.py`` and ``catchment/raster_support.py``.
``support_fields.py`` reads ``model/properties/`` (``Field`` and ``cell_sampling``) and
``mesh/planar/planar_cell_mesh.py``, and ``spatial_support.py`` reads ``support_fields.py`` and
the support config. ``capability.py`` reads ``schema``, ``depth_model_config.py`` and
``job_inputs.py``. ``worker.py`` reads ``schema`` and ``job_inputs.py``, and
``catchment/algorithms/surface_from_dem.py`` for the top surface. ``active_cells.py`` reads
``core`` and ``schema.job.refusal``, and ``domain_document.py`` reads ``capability.py`` and
nothing else from HydroModPy. ``structure_binders.py`` reads ``catchment/algorithms/`` and names
``Domain`` and ``GeologyField`` for typing only. ``lake_bed_abacus.py`` reads only
``core.logging``, and ``lake_bed_regrid.py`` reads it, ``catchment/surface.py`` and
``catchment/surface_sampling.py`` and takes the mesh as an argument. Nothing in ``properties/``
imports ``domain/``.

Inside ``properties/``, ``geology_config.py`` reads ``core`` and no mesh. ``field_param_io.py``
reads ``field_param.py``, ``core.config_kit.field_param.config`` and ``field_spatial.py``.
``field_param.py`` reads ``core.units``, ``core.config_kit.field_param.units``, ``mesh_cells.py``
and ``vertical_profile.py``, and ``vertical_profile.py`` reads ``mesh_cells.py`` and
``core.units``. ``mesh_cells.py``, ``plotting.py``, ``field_spatial.py``, ``zone_fractions.py``
and ``unit_square_mesh.py`` read the mesh model, and the mesh never imports this package.
``cell_sampling.py`` reads ``mesh_cells.py`` and imports ``PlanarCellMesh`` for typing only.
``geology_field.py`` imports no ``data`` module. ``property_table.py`` reads ``property_ids.py``,
``time/regime.py``, ``field_spatial.py``, ``zone_fractions.py`` and ``core``.

Inside ``forcing/``, ``cells.py`` is the entry point of the cells path. It reads ``rasters.py``,
``sources.py`` and ``stations.py``. ``rasters.py`` and ``stations.py`` read ``sources.py``, and
``sources.py`` reads ``area_weights.py`` and ``interpolation.py``, which import no other module of
the package. ``recharge_rates.py`` imports ``core`` only. On the series path,
``forcing_bridge.py`` reads ``cells.py``, ``time_alignment.py``, ``types.py`` and
``model/contracts.py``. ``time_forcing.py`` reads ``dated_forcing.py`` and ``time_alignment.py``,
and ``steady_periods.py`` reads ``types.py``. ``time_alignment.py`` reads only ``core.time``, and
``soil_config.py`` reads no other module of the package. ``area_weights.py`` reads
``derive_geometry`` from ``mesh/planar/geometry.py``, and imports ``HydroMesh`` and
``ResolvedSimulationTimeWindow`` for type hints only. xarray, rasterio, pyproj and the scipy
interpolators are imported inside the functions that use them, so a run without a grid forcing
does not load them.

What lives outside the package
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The setup step, ``workflow/steps/setup.py``, builds the domain of a run (``build_domain``) and
rebuilds it (``rebuild_domain``) when it is stale or when the depth model of a trial moved. It
also builds the supports of a phase (``build_phase_supports``). The solvers read the layering
through ``solver/modflow_grid/discretization_spatial.py``, which calls ``layer_stack`` and
``assert_bottom_below_top``. The caller of the lake bed is ``carve_lake_bed`` in
``solver/modflow6/builders/lake_cells.py``. It reads the ``bed_reconstruction`` table of each lake
and imports the two lake bed modules inside the function, so a run without a lake bed never loads
them. The ``[domain]`` config is a field of ``HydroModPyConfig``, and the calibration reads the
depth models in ``calibration/parameter_resolution.py``. The demo that builds a ``Domain`` from a
project TOML lives in ``tools/cases/domain/``, and the geology demo that goes through
``FieldParam`` is ``tools/cases/geology/run_geology_property_case.py``.

The recharge and ETP packages of the solvers call the cells path
(``solver/modflow6/builders/recharge.py``, ``solver/modflow_nwt/nwt/payloads/recharge_etp.py`` and
``solver/boussinesq/forcing/recharge_resolution.py``). The workflow step
``workflow/steps/prepare_solver/forcings.py``, the recharge binder of
``model/boundaries/climate.py`` and ``calibration/metrics/series.py`` use the spatial mean.
``forcing/interpolation.py`` is also used by the Explore2 client in
``data/common/clients/explore2_files.py``. The solvers call ``property_table.py`` from their
builders, for example ``solver/modflow6/support/property_mapping.py``, and the flow config embeds
the field-parameter sections in ``FlowParam`` (``model/flow_config.py``). The transport solvers
live in the folders of the flow backends they follow. They receive the frozen ``Model`` of their
flow, their own options and the run slot through the adapter contract, and the runner reads the
table of a run with ``options_of(name)``.

Where to add what
~~~~~~~~~~~~~~~~~

A flow parameter is a field on ``FlowConfig`` with a profile and a description, as
:doc:`../how-to/add-a-config-field` says. A boundary id is an entry of
``FLOW_BOUNDARY_DEFINITIONS`` in ``boundaries/boundary_condition_registry.py``, then the solver
that builds it. A sink or source kind is a payload module in ``sinks_sources/``, a field on
``FlowSinksSourcesConfig`` in ``container.py`` and a ``Flow.sinks_sources`` key in
``Flow.set_sinks_sources``. A way to bring loaded data into a ``Flow`` is an ``apply_*_to_flow``
function in the module of ``boundaries/`` it belongs to, called from ``workflow/steps/data.py``.
An initial-condition type is a model in ``initial_config.py``, added to ``_IC_VARIANTS`` and to
the union, and a state in ``initial/state.py``. A field the solvers read is a member of ``Model``
in ``model.py``, filled by ``model_from_flow``. A new process is a subpackage with its own runtime
class and a config on ``HydroModelBase``, as ``flow.py`` and ``flow_config.py`` do, and
:doc:`../how-to/add-a-process` gives the recipe. A depth model is a model in
``depth_model_config.py``, and a support kind starts in ``spatial_support_config.py``, then a
provider in ``spatial_support.py``. A soil-reservoir option is a field on ``SoilReservoirConfig``
(``forcing/soil_config.py``), its bound in ``_RANGE_RULES``, and its use in ``soil/kernel.py`` or
``forcing/soil_forcing.py``. A new key of the field-parameter TOML is a field of a Pydantic model
in ``core/config_kit/field_param/sections.py`` with its description, and the parameter reference
is built from the models.

Tests
~~~~~

The unit tests mirror the code under ``tests/unit/model/``, and a test file carries the name of
the module it tests. They build their grids, surfaces, layerings, masks, cell centers, gridded
records and cell meshes with the helpers ``tests/_helpers/domain_cases.py``,
``lake_bed_cases.py``, ``forcing_cases.py`` and ``field_cases.py``. The worker is tested in
``tests/integration/domain/test_worker.py``, and the soil kernel in
``tests/unit/model/soil/test_soil_kernel.py``. The job ``Coverage / floors per sub-package`` of
``.github/workflows/main-ci.yml`` keeps a coverage floor for each sub-package of ``model/`` in
``tools/ci/coverage_floors.toml``, and the floors only go up. The theory pages are
:doc:`/theory/groundwater-flow` for the top, the bottom and the layers, :doc:`/theory/mesh` for
the layers by surfaces and the pinch-out, :doc:`/theory/exits/lakes` for the active shore and the
carved bed, :doc:`/theory/forcing` for the periods, the coverage rule and the cell methods,
:doc:`/theory/solvers/field-to-cell-parameter-transfer` for the field transfer and
:doc:`/theory/soil-reservoir` for the reservoir. The support pages are in
:doc:`../spatial_support/spatial-support-uml-diagrams`, and the developer page of the field layer
is :doc:`../field/index`.

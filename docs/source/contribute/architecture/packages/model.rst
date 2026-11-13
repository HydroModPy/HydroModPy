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

How a flow is built
~~~~~~~~~~~~~~~~~~~

``FlowConfig.from_toml_section`` in ``flow_config.py`` canonicalizes the boundary ids, resolves
the forcing paths and validates the ``[flow]`` table. Then ``Flow(config=cfg.flow)`` runs
``set_config``. It fills the parameters (``FieldParam`` objects), the initial and boundary
conditions and the sinks and sources, and it converts the well fluxes and the recharge to SI.
``ensure_flow`` in ``workflow/steps/data.py`` builds it at setup.

After the data step, ``workflow/steps/data.py`` calls the ``apply_*_to_flow`` functions of
``boundaries/``. They put the loaded data on the ``Flow``, and the same cascade runs for a trial.

Then ``model_from_flow`` in ``model.py`` returns a ``Model``. It holds the same objects as the
``Flow``, in SI, with the geometry, the time grid and the shared solver options beside them. A
prior run is read into a ``PriorState`` there, and the river network A is read on the cells
(``Geometry.channel_exits``). So no adapter opens a Zarr store or projects A itself.

A solver adapter reads the ``Model`` and never the ``Flow``. A change to the model is a new
object (``with_properties``, ``steady_variant``, ``cycle_variant``).

The domain
~~~~~~~~~~

The domain is the aquifer as a body of rock. The mesh decides the cells in the plan, and
``domain/`` decides what is above and below each cell. ``build_domain`` in ``build.py`` is the one
constructor of a ``Domain``, called by the setup step and the ``domain-build`` capability.
``layering.py`` turns ``[domain.layers]`` and the two surfaces into the bottom and the ``idomain``
of every layer. It works on arrays only, so it knows no ``Domain``.

``structure_binders.py`` writes the geology and the catchment zones into the domain once the data
is loaded. The zones are a ``CatchmentZonesField``, defined in
``catchment/algorithms/catchment_zones_field.py`` beside the code that computes them. A
heterogeneous parameter asks for a support, which ``spatial_support.py`` builds.

The lake bed rebuilt from a bathymetry raster lives here because it changes the top and the
layers of the cells under a lake. ``carve_lake_bed`` in ``solver/modflow6/builders/lake_cells.py``
calls it and imports the two lake bed modules inside its body.

The ``domain-build`` capability runs ``build_domain`` as a job for outside tools. No ``hmp``
command starts it and only ``tests/integration/domain/`` calls it here, but keep it.

Properties and forcing
~~~~~~~~~~~~~~~~~~~~~~

A ``FieldParam`` holds the values of one parameter in SI units, one per zone, and its depth
profile. ``FieldParam.to_mesh_field`` weights the zone values with the zone share of each cell
(a ``Field`` of ``field_spatial.py``) and returns a ``MeshWithValues``. ``map_flow_properties`` in
``property_table.py`` does this for K, Kv, Sy, Ss and the K tensor of every solver, and it refuses
a value that is not positive.

A forcing reaches a solver by two paths. A grid or a set of stations goes through
``discretize_fields_on_cells`` in ``forcing/cells.py``. It gives one rate per cell and per stress
period, in m/s, whatever the mesh engine. A CRS other than the mesh CRS is refused, because a grid
is never reprojected. The ``area`` method weighs each pixel by the area it shares with the
cell, so a cell rate times its area is the integral of the grid. A series that does not go through a mesh is aligned to the stress periods
by ``time_alignment.py`` and resolved by
``time_forcing.resolve_period_values_from_forcing``. ``steady_periods.py`` is the one rule every
solver shares for a steady period. xarray, rasterio, pyproj and the scipy interpolators are
imported inside the functions that use them, so a run without a grid forcing does not load them.

The soil reservoir
~~~~~~~~~~~~~~~~~~

The daily soil reservoir makes a recharge from the weather before the groundwater solve.
``soil/kernel.py`` holds the arithmetic, one function per equation with its reference. It is a
science module, so it needs only numpy and reads from top to bottom. The rest sits in ``forcing/``
(``soil_*.py``) because it reads the records that a project loads, through ``contracts.py``, so
nothing here imports ``data``. ``soil_forcing.compute_soil_forcings`` runs the kernel day by day.
The soil applies to MODFLOW 6 only. The PyHELP recharge model sits in
``hydromodpy_annex/physics/pyhelp/``.

Boundaries of the package
~~~~~~~~~~~~~~~~~~~~~~~~~

The model never imports ``data``, ``results`` or ``solver``. It sees loaded data through the
``LoadResultProto`` and ``FieldRecordProto`` of ``contracts.py``. Inside the package,
``boundaries/`` reads ``flow.py`` for annotations only, and this is the one cycle. ``soil/`` and
``initial/`` are science folders, where a module may import only numpy and one neighbour of its
folder, and ``tests/unit/architecture/test_science_module_imports.py`` holds it. Nothing in
``properties/`` imports ``domain/``, and the mesh never imports this package. The import table is
the generated page :doc:`../generated/layers`.

Where to add what
~~~~~~~~~~~~~~~~~

A flow parameter is a field on ``FlowConfig`` with a profile and a description, as
:doc:`../how-to/add-a-config-field` says. A boundary id is an entry of
``FLOW_BOUNDARY_DEFINITIONS`` in ``boundaries/boundary_condition_registry.py``, then the solver
that builds it. A sink or source kind is a payload module in ``sinks_sources/``, a field on
``FlowSinksSourcesConfig`` in ``container.py`` and a key in ``Flow.set_sinks_sources``. A way to
bring loaded data into a ``Flow`` is an ``apply_*_to_flow`` function in ``boundaries/``, called
from ``workflow/steps/data.py``. An initial-condition type is a model in ``initial_config.py``,
added to ``_IC_VARIANTS`` and to the union, and a state in ``initial/state.py``. A field the
solvers read is a member of ``Model``, filled by ``model_from_flow``. A new process is a
subpackage with its own runtime class and a config on ``HydroModelBase``, and
:doc:`../how-to/add-a-process` gives the recipe. A depth model is a model in
``depth_model_config.py``, and a support kind starts in ``spatial_support_config.py``, then a
provider in ``spatial_support.py``. A soil-reservoir option is a field on ``SoilReservoirConfig``
in ``forcing/soil_config.py``, its bound in ``_RANGE_RULES``, and its use in ``soil/kernel.py`` or
``forcing/soil_forcing.py``. A new key of the field-parameter TOML is a field of a Pydantic model
in ``core/config_kit/field_param/sections.py`` with its description.

Tests
~~~~~

The unit tests mirror the code under ``tests/unit/model/``. To read the property layer, start at
``field_spatial.py``, then ``field_param.py``, and run ``tools/cases/field/square/``.

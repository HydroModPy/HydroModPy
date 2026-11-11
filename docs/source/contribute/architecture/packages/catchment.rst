Package: catchment
==================

.. include:: ../../../../../hydromodpy/catchment/README.md
   :parser: myst_parser.sphinx_
   :start-line: 1

Modules
-------

.. hmp-module-table:: catchment

Inside the package
------------------

The parts
~~~~~~~~~

The parts are listed lowest first, and a part reads only the parts above it.
``catchment_layout.yaml`` in ``tests/unit/architecture/`` holds the same order. At the root,
``raster_support.py`` says where a 2D surface sits (``RasterSupport``), ``surface.py`` holds the
surfaces of the domain (``Surface``) and ``surface_sampling.py`` holds samplers prepared for
repeated reads at points. ``administrative/`` holds the French departments and regions of the
bundled ``departement.gpkg``, with their codes in a box or a region, their box and their outline.
``delineation/`` holds the one Whitebox Workflows environment of the process, in
``whitebox_workflows_backend/``, and the two helpers that read a backend. ``terrain/`` holds the
``TerrainEngine`` port, its two engines (Whitebox and numpy), the artifact writers, the D8 pointer
reader, the DEM header contract and the undrained-cell count, and it has its own README.
``algorithms/`` holds one module per processing block, which are the ground, the flow products,
the catchment, the zones, the river and hydrographic networks, the lakes and the SFR reaches.
``synthetic/`` holds analytic catchments with no DEM, for validation, and
``[geographic.synthetic]``. ``preprocess/`` holds the pipeline before the simulation, which is the
run, the geographic tree, the ``[geographic]`` configuration and the runtime objects others read.
``drainage/`` says where water goes on the cells of the model top. It holds the receiver graph,
depression filling, the descent D, the downslope distance, the channel tree of the river network A
(``channel_tree.py``) and the routing of a release to a discharge (``routing.py``).
``stream_network/`` holds the stream-network criterion on arrays, which is the simulated network,
the flowing cells and the extent masks, the mapped network drawn from its heads, the geometry of a
comparison and its partition, and the signed cost a trial is scored on. The ``__init__.py`` files
hold a docstring and export no name, so a name is imported from the module that defines it, for
example ``GeographicConfig`` from ``preprocess/geographic_config.py``.

The Whitebox backend
~~~~~~~~~~~~~~~~~~~~

``delineation/whitebox_workflows_backend/`` wraps Whitebox Workflows in a facade,
``WhiteboxWorkflowsBackend``, with three parts that share one Whitebox environment. ``raster``
reads and writes files, ``flow`` runs the depressions, the D8 pointer and the accumulation, and
``delineation`` snaps pour points and traces watersheds and streams. Only ``raster.py`` and the
child script ``depression_child.py`` import ``whitebox_workflows``.

A process holds one facade. ``get_whitebox_backend()`` in ``delineation/__init__.py`` builds it on
the first call, and ``clear_whitebox_backend_cache()`` drops it. Importing ``delineation`` does
not load Whitebox, so a caller that needs a class of the backend imports it from
``whitebox_workflows_backend``. A function that takes a backend as an argument receives it from
``resolve_delineation_backend(backend)``, which returns the argument when there is one.

Whitebox 1.3.5 can end the process that calls it, with no exception, when two of its threads race
in a depression tool. So ``isolated.py`` runs depression removal in a child Python process, and
the parent runs it again after a crash, three attempts in all.

How a preprocess run goes
~~~~~~~~~~~~~~~~~~~~~~~~~

A preprocess run has seven steps. ``preprocess/pipeline.py`` runs them and ``algorithms/`` holds
the code of each one.

1. ``preprocess/pipeline_steps.py`` receives ``dem_path`` from the caller, checks the DEM header
   and the outlet through ``terrain/dem_contract.py``, resolves the output paths, reads the CRS
   and the cell size of the DEM, and aggregates the DEM to a coarser cell when
   ``[geographic.catchment]`` asks for it.
2. The run asks the product store for the terrain, which is the conditioned DEM with its D8
   directions and its accumulation, keyed by the digest and state of the DEM, the method, the
   engine and the code. A present product is read back into the run tree and the conditioning of
   step 4 is skipped.
3. ``algorithms/ground_corrections.py`` builds the ground, which is the DEM plus the corrections
   the project declares. Without a correction it is the raw DEM, with no copy.
4. ``algorithms/flow_products.py`` conditions the ground (fill, breach or capped breach, or
   ``provided`` for a DEM declared conditioned elsewhere) and computes the D8 direction and
   accumulation rasters through a terrain engine. ``algorithms/terrain_stored.py`` writes a
   missing product.
5. ``algorithms/catchment_from_point.py`` delineates the catchment, or
   ``algorithms/direct_dem_domain.py`` takes the DEM extent. ``algorithms/catchment_domain.py``
   cuts the buffered and box polygons, and ``algorithms/river_network.py`` extracts the streams.
6. When ``[geographic.crossings]`` is on, ``algorithms/crossing_notch.py`` lowers the embankments
   where they cross the channel, and the delineation runs a second time on the notched ground.
   Then ``preprocess/domain_rasters.py`` clips the DEM rasters to the domain polygons. When
   ``[geographic.bed_regularization]`` is on, ``algorithms/ground_bed.py`` fits the channel bed.
7. ``algorithms/dem_metadata.py`` reads the metadata of the clipped rasters, and ``pipeline.py``
   returns one ``GeographicRuntimeContext``.

``source_mode = "synthetic"`` skips all of this. ``synthetic/catchment.py`` builds the support
from the ``[geographic.synthetic]`` table and returns a ``SyntheticGeographic`` object with the
same public attributes.

The runtime object that others read is ``CatchmentDelineation``, in
``preprocess/catchment_delineation.py``. The workflow step ``BuildGeographicStep`` in
``hydromodpy/workflow/steps/setup.py`` is the caller, and it passes the resolved ``dem_path`` to
the pipeline. The tree lives in the preprocessing folder of the run, and
``preprocess/preprocessing_cleanup.py`` removes it once the run holds what it needs, unless
``write_intermediates`` keeps it. ``algorithms/geographic_paths.py`` holds every output path of
the tree, and ``preprocess/geographic_tree.py`` lists the files a resume must find, by name.

From a catchment to a mesh
~~~~~~~~~~~~~~~~~~~~~~~~~~

``[geographic]`` (``GeographicConfig``) drives the run above, and the artifacts are kept in the
workspace and reused when the inputs have not changed. ``hydromodpy/model/domain/build.py`` is the
one constructor of a ``Domain`` from a ``DomainConfig`` (``[domain]``), a surface and a depth
model. The zones come later, from ``model/domain/structure_binders.py``, which reads
``algorithms/catchment_zones_field.py`` and the geology field its caller brings. ``[mesh]`` then
picks an engine in ``hydromodpy/mesh``. Triangles and Voronoi cells follow the zones and the river
trace, and the regular grid makes a staircase along them. The planner reads the river lines
through ``resolve_river_mesh_trace`` in ``algorithms/derived_features.py``. A ``FieldParam`` is
discretized on the mesh in ``model/``, and a solver reads the cells through its
``solver/modflow_grid/`` description.

Rules between the modules
~~~~~~~~~~~~~~~~~~~~~~~~~

``tests/unit/architecture/layer_matrix.yaml`` gives the package ``core``, ``schema`` and itself.
No module reads ``data``. The DEM path is passed as an argument by the caller, and the reader of
one vector geology map is a function the caller passes as an argument, as the mesh planner shows.
Another layer of HydroModPy may import only the modules listed under ``public`` in
``catchment_layout.yaml``. The inside of the pipeline stays private (``preprocess/pipeline.py``,
``pipeline_steps.py``, ``domain_rasters.py``, ``subbasin.py`` and the small configurations it
composes).

Five more rules hold inside. First, ``terrain/`` imports ``core`` and itself, and one thing more.
``WhiteboxTerrainEngine.__init__`` imports ``catchment.delineation`` inside the function, and only
when it is given no backend. A third-party engine needs nothing of HydroModPy but the port module,
and ``tests/unit/architecture/test_layers.py`` checks it. Second, ``drainage/`` imports ``core``,
itself, ``terrain/`` and ``algorithms/``. ``hydromodpy/mesh/planning/height_above_stream.py``
reads it, and ``terrain/`` and ``preprocess/`` do not, because they work on D8 pixels before the
mesh exists. ``channel_tree.py`` reads the D8 table of ``terrain/`` and the pointer name of
``algorithms/flow_products.py``. Third, ``algorithms/`` reads no configuration of the pipeline.
A module there takes the config it needs as an argument. Fourth, a third-party terrain engine joins
through the entry-point group ``hydromodpy.terrain.engine``, and the conformance suite
``tests/ports/test_terrain.py`` runs on every engine the registry resolves. Fifth,
``stream_network/`` imports ``core``, itself, ``drainage/`` and ``algorithms/``. It is a science
folder under rule 6 of the repository, and the imports it still needs outside numpy and one
neighbour are listed one by one in the table ``ALLOWED_OUTSIDE`` of
``tests/unit/architecture/test_science_module_imports.py``. That table can only shrink. The
readers of the criterion on a stored run stay in ``results/derive/stream_network/``.

Who reads the package
~~~~~~~~~~~~~~~~~~~~~

``solver`` and ``workflow`` import ``catchment`` most, then ``model``, ``mesh``, ``results``,
``calibration``, ``config``, ``project`` and ``data``. The demos that load a whole project TOML
live outside the package, in ``tools/cases/``.

Where to add what
~~~~~~~~~~~~~~~~~

A Whitebox tool is a method of the part it belongs to in
``delineation/whitebox_workflows_backend/``, written as a pair, a ``*_raster`` or ``*_vector``
method on objects in memory and a method that reads and writes files. A depression tool that can
end the process also goes to ``DEPRESSION_TOOLS`` in ``isolated.py``. A terrain engine is a class
that satisfies the port in ``terrain/port.py``, registered by ``terrain_engines.register`` in
``terrain/registry.py`` or on the ``hydromodpy.terrain.engine`` entry-point group. A geographic
product is a module in ``algorithms/``, called from ``preprocess/pipeline.py``, with a field on
``GeographicConfig`` for its options. A ``[geographic]`` key is a field of the Pydantic model in
``preprocess/geographic_config.py`` or in the file of its sub-table, with its description. The
name or place of an output file is in ``algorithms/geographic_paths.py``. A synthetic topography
goes to ``synthetic/synthetic_config.py``, then ``synthetic/topography.py``. A routing rule or a
distance on the model top goes to ``drainage/graph.py``, ``drainage/descent.py``,
``drainage/distance.py`` or ``drainage/routing.py``. A rule of the stream-network criterion goes
to the module of ``stream_network/`` that owns it, with its defaults in
``core/scoring/stream_defaults.py``. The way the river network A is read or pinned on the cells is
in ``drainage/channel_tree.py``. Another country for the departments is a new module beside
``administrative/france.py``. A mesh engine is a class that satisfies the port in
``hydromodpy/mesh/port.py``, as :doc:`../mesh/mesh-engines` says. A capability is a
``CapabilityDecl`` and a worker beside the code, as ``hydromodpy/schema/README.md`` says.

Tests
~~~~~

The tests mirror the code under ``tests/unit/catchment/``. A module of ``algorithms/`` is tested
in ``tests/unit/catchment/algorithms/`` and one of ``preprocess/`` in
``tests/unit/catchment/preprocess/``. The delineation signatures that the unit tests compare to
are in ``tests/unit/catchment/preprocess/golden/``. A test builds its DEMs, configs and geographic
trees with the helpers of ``tests/_helpers/geographic_cases.py``. The CI runs
``tests/unit/catchment/delineation/whitebox_workflows_backend/test_whitebox_workflows_backend.py``
in its own step, apart from the rest of the suite, because the Whitebox binding is not safe under
pytest-xdist fork distribution. The job ``Coverage / floors per sub-package`` of
``.github/workflows/main-ci.yml`` keeps a coverage floor for each sub-package of ``catchment/`` in
``tools/ci/coverage_floors.toml``, and the floors only go up. The parameter reference of the table is
``docs/source/reference/parameters/geographic.md``, and ``CatchmentDelineation`` is documented in
``docs/source/reference/python/CatchmentDelineation.md``. The network objects of ``algorithms/``
are described in :doc:`../spatial_support/spatial-support-uml-diagrams`.


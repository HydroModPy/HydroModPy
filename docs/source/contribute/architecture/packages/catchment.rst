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

The Whitebox backend
~~~~~~~~~~~~~~~~~~~~

``delineation/whitebox_workflows_backend/`` wraps Whitebox Workflows in one facade,
``WhiteboxWorkflowsBackend``, built once per process by ``get_whitebox_backend()`` in
``delineation/__init__.py``. Importing ``delineation`` does not load Whitebox, so a caller that
needs a class of the backend imports it from ``whitebox_workflows_backend``. Only ``raster.py``
and the child script ``depression_child.py`` import ``whitebox_workflows``.

Whitebox 1.3.5 can end the process that calls it, with no exception, when two of its threads race
in a depression tool. So ``isolated.py`` runs depression removal in a child Python process, and
the parent runs it again after a crash, three attempts in all.

How a preprocess run goes
~~~~~~~~~~~~~~~~~~~~~~~~~

``preprocess/pipeline.py`` runs the steps and ``algorithms/`` holds the code of each one.

1. ``pipeline_steps.py`` checks the DEM header and the outlet through ``terrain/dem_contract.py``
   and aggregates the DEM to a coarser cell when ``[geographic.catchment]`` asks for it.
2. The run asks the product store for the terrain, which is the conditioned DEM with its D8
   directions and its accumulation, keyed by the digest of the DEM, the method, the engine and the
   code. A present product is read back and the conditioning of step 4 is skipped.
3. ``algorithms/ground_corrections.py`` builds the ground, which is the DEM plus the corrections
   the project declares.
4. ``algorithms/flow_products.py`` conditions the ground and computes the D8 direction and
   accumulation rasters through a terrain engine. ``terrain_stored.py`` writes a missing product.
5. ``algorithms/catchment_from_point.py`` delineates the catchment, or ``direct_dem_domain.py``
   takes the DEM extent. ``catchment_domain.py`` cuts the polygons and ``river_network.py``
   extracts the streams.
6. When ``[geographic.crossings]`` is on, ``crossing_notch.py`` lowers the embankments where they
   cross the channel, and the delineation runs a second time on the notched ground. Then
   ``preprocess/domain_rasters.py`` clips the rasters to the domain. When
   ``[geographic.bed_regularization]`` is on, ``ground_bed.py`` fits the channel bed.
7. ``dem_metadata.py`` reads the metadata of the clipped rasters, and ``pipeline.py`` returns one
   ``GeographicRuntimeContext``.

``source_mode = "synthetic"`` skips all of this. ``synthetic/catchment.py`` returns a
``SyntheticGeographic`` with the same public attributes. The runtime object that others read is
``CatchmentDelineation``, and ``BuildGeographicStep`` in ``workflow/steps/setup.py`` is the caller.
``preprocessing_cleanup.py`` removes the tree once the run holds what it needs, and
``geographic_tree.py`` lists the files a resume must find.

From a catchment to a mesh
~~~~~~~~~~~~~~~~~~~~~~~~~~

``hydromodpy/model/domain/build.py`` builds a ``Domain`` from the surface, and
``model/domain/structure_binders.py`` adds the zones later. ``[mesh]`` then picks an engine in
``hydromodpy/mesh``. Triangles and Voronoi cells follow the zones and the river
trace, and the regular grid makes a staircase along them. The planner reads the river lines
through ``resolve_river_mesh_trace`` in ``algorithms/derived_features.py``.

Boundaries of the package
~~~~~~~~~~~~~~~~~~~~~~~~~

The package reads ``core`` and ``schema`` only, and never ``data``, so the caller passes the DEM
path and the reader of a vector geology map as arguments. The import table is the generated page :doc:`../generated/layers`. Another layer may import only the
modules listed under ``public`` in ``tests/unit/architecture/catchment_layout.yaml``. The inside
of the pipeline stays private.

Four rules hold inside. First, ``terrain/`` imports ``core`` and itself, and one thing more.
``WhiteboxTerrainEngine.__init__`` imports ``catchment.delineation`` inside the function, and only
when it is given no backend. So a third-party engine needs nothing of HydroModPy but the port
module. Second, ``drainage/`` reads ``terrain/`` and ``algorithms/``, and ``terrain/`` and
``preprocess/`` do not read it, because they work on D8 pixels before the mesh exists. Third,
``algorithms/`` reads no configuration of the pipeline, so a module there takes the config it
needs as an argument. Fourth, ``stream_network/`` is a science folder under rule 6. The imports it
still needs outside numpy and one neighbour are listed in ``ALLOWED_OUTSIDE`` of
``tests/unit/architecture/test_science_module_imports.py``, and that table can only shrink.

Where to add what
~~~~~~~~~~~~~~~~~

A Whitebox tool is a method of the part it belongs to in
``delineation/whitebox_workflows_backend/``, written as a pair, a ``*_raster`` or ``*_vector``
method in memory and a method that reads and writes files. A depression tool that can end the process also goes to
``DEPRESSION_TOOLS`` in ``isolated.py``. A terrain engine is a class that satisfies the port in
``terrain/port.py``, registered by ``terrain_engines.register`` in ``terrain/registry.py`` or on
the ``hydromodpy.terrain.engine`` entry-point group, and ``tests/ports/test_terrain.py`` runs on
every engine the registry resolves. A geographic product is a module in ``algorithms/``, called
from ``preprocess/pipeline.py``, with a field on ``GeographicConfig`` for its options. A
``[geographic]`` key is a field of the Pydantic model in ``preprocess/geographic_config.py`` or in
the file of its sub-table, with its description. An output path is in ``algorithms/geographic_paths.py``. A routing rule or a distance on the model top goes to
``drainage/``, and the way the river network A is read on the cells is in
``drainage/channel_tree.py``. A rule of the stream-network criterion goes to the module of
``stream_network/`` that owns it, with its defaults in ``core/scoring/stream_defaults.py``. A mesh
engine satisfies the port in ``hydromodpy/mesh/port.py``, as :doc:`../engines/mesh-engines` says.

Tests
~~~~~

The tests mirror the code under ``tests/unit/catchment/`` and build their DEMs and trees with
``tests/_helpers/geographic_cases.py``. The CI runs
``tests/unit/catchment/delineation/whitebox_workflows_backend/test_whitebox_workflows_backend.py``
in its own step, because the Whitebox binding is not safe under pytest-xdist fork distribution.

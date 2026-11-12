Package: data
=============

.. include:: ../../../../../hydromodpy/data/README.md
   :parser: myst_parser.sphinx_
   :start-line: 1

Modules
-------

.. hmp-module-table:: data

Inside the package
------------------

The subpackages
~~~~~~~~~~~~~~~

The subpackages are listed lowest first. ``contracts/`` holds the records handed upward, which are
``PointRecord``, ``FieldRecord``, ``TableRecord`` and ``LoadResult``. ``schemas/`` holds the
pandera schemas of the input tables (stations, chronicles, abacus, lithology, DEM), each with its
``validate()``. ``source/`` holds the ``DataSource`` port and the registry of sources, plugins
included, with the generic ``file`` and ``url`` sources, and it has its own README. ``common/``
holds functions with no variable config and no cache, which are HTTP, units, geometry, file naming
and the one mask loader (``source_extent.py``). Its ``clients/`` folder holds what several
variables share, which is the SIM2 product table and download, the Hub'Eau station helpers and the
local DRIAS Explore2 NetCDF reader (``explore2_files.py``, read by ``precipitation`` and ``etp``).
``ingest/`` turns a user file into the storage format and into records, for rasters, vectors,
tables, station folders and grids, and it holds the observation series a run keeps beside the
simulated ones (``observations.py``). ``provenance/`` holds what sits next to a file on disk and
the cache that is made of it, which is the sidecars and ``CacheIndex`` (``sidecars.py``), the
derived copies, ``hydromodpy.lock`` (``lockfile.py``) and the cache archive (``archive.py``).

``families/`` holds the bases the variables inherit, which are the shared state, the cache calls
and the ``FetchRequest`` the family builds and hands to the class of the source port.
``variables/`` holds one package per ``[data.<name>]`` section, and four flat modules that each
hold a family of thin variables. They are ``sim2_series.py`` (wind, humidity, runoff, soil
moisture, temperature), ``forcing_series.py`` (radiation, ETP, precipitation), ``lake_series.py``
(lake levels, inflow, outflow, withdrawal) and ``user_rasters.py`` (soil capacity, substratum,
layer base). ``sites/`` holds the sites of the workspace. ``loading/`` goes from ``[data]`` of the
TOML to the variables it activates and to the data loaded, with ``DataConfig``, ``DataPlanner``,
``DataLoader`` and ``DataStore``. ``workspace/`` holds the workspace data folder, which is the
scaffold of file templates and ``folders.py``, the creation, listing, deletion and cleaning of
workspace and project folders behind ``hmp workspace init``, ``hmp workspace clean``, ``hmp
project new``, ``hmp project list`` and ``hmp project delete``. ``request/`` serves data asked for
from outside a project and is the one subpackage that reads the workspace, ingest, provenance and
loading together.

The variables
~~~~~~~~~~~~~

Each ``[data.<name>]`` section of a project TOML is one variable, and ``VARIABLE_SPECS`` in
``loading/_dispatch.py`` is the single list of them. There are ten grid variables
(``precipitation``, ``etp``, ``temperature``, ``wind``, ``humidity``, ``radiation``,
``soil_moisture``, ``runoff``, ``recharge`` and ``oceanic``), four station variables
(``hydrometry``, ``piezometry``, ``water_quality`` and ``intermittency``), three terrain and
subsurface variables (``dem``, ``geology`` and ``hydrography``), one structure variable
(``crossings``), four lake chronicles (``lake_inflow``, ``lake_levels``, ``lake_outflow`` and
``lake_withdrawal``), and six user files, which are ``lake_abacus`` (a table),
``lake_bathymetry``, ``substratum``, ``soil_capacity`` and ``layer_base`` (rasters) and
``lake_geometry`` (a vector). The sources besides ``file`` that each one accepts are in the
generated catalog of data sources, :doc:`/reference/data-sources`. Every value of the ``source``
field is a key of ``data_sources`` for its section, the two-part key of ``source/``, alongside the
``file`` source that every section accepts. The variable still owns its cache, whatever the
source. Grids are kept in ``GridVariable``, stations in ``StationVariable`` and user files in
``FileVariable``.

``StationVariable`` serves ``hydrometry``, ``piezometry``, ``water_quality``, ``intermittency``
and the four lake chronicles. It keeps one chronicle per station and asks only for the missing
periods. ``GridVariable`` serves the SIM2 and Explore2 variables, ``recharge`` and ``oceanic``,
and keeps one NetCDF or GeoTIFF per box and period. ``FileVariable`` serves the variables read
only from the user's own file, which are ``lake_abacus``, ``lake_geometry`` and the rasters, and
``RasterFileVariable`` is its base for rasters. ``dem``, ``geology``, ``hydrography`` and
``crossings`` are written by hand and inherit only ``SourceTable``, the ``SOURCES`` dispatch of
``families/common.py``.

Five SIM2 grid variables (``temperature``, ``humidity``, ``runoff``, ``soil_moisture`` and
``wind``) share ``Sim2GridSourceConfig``, and the four lake chronicles share
``LakeChronicleSourceConfig``. A subclass declares its own ``path`` field, because the ``role`` of
its ``InputFile`` is the variable name and that role is part of the TOML schema. The JSON schema
of ``[data]`` is pinned by ``tests/unit/data/test_data_surfaces.py``, so a moved
field or a changed description changes its digest.

The template of a variable
~~~~~~~~~~~~~~~~~~~~~~~~~~

A variable that is a package follows this template.

.. code-block:: text

   variables/<v>/
   ├── __init__.py   a one-line docstring, no import: validating a TOML loads no variable
   ├── config.py     <V>Config and <V>SourceConfig; the `source` field is a name of the registry
   ├── variable.py   VARIABLE_NAME, INTERNAL_UNIT, the FetchRequest of the section
   ├── apis/         one module per network provider of the variable, if it has one
   └── file.py       only when loading the user's files takes real work

A thin variable has no code of its own. It is a source config, a section config and a variable
class that names itself, so it does not get a folder. Its three classes sit in the flat module of
its family, one section per variable with the same three names (``<V>SourceConfig``, ``<V>Config``
and ``<V>Variable``, and ``File<V>Source`` and ``Url<V>Source`` for a raster the user brings). The
first ``VARIABLE_SPECS`` entry of a variable points ``config_module`` and ``variable_module`` at
that module. A variable that gets a provider, a resolver or a loader of its own moves to a folder.
``dem``, ``crossings`` and ``hydrography`` also keep a ``resolver.py``, because the geographic
step runs before any variable loads, so it turns their sources into files on disk first
(``resolve_dem``, ``fill_crossings_path`` and ``resolve_network_map_path``).

A variable names itself and the unit its records carry, and it leaves every provider to the
registry of sources.

.. code-block:: python

   class HydrometryVariable(StationVariable):
       VARIABLE_NAME = "hydrometry"
       INTERNAL_UNIT = "m3/s"
       RECORD_VARIABLE = "discharge"

``RECORD_VARIABLE`` is optional. It names what a record carries when that differs from
``VARIABLE_NAME``. ``data_sources.get(VARIABLE_NAME, cfg.source)`` answers the class, and
``build_from_section`` binds the fields of the section to its constructor. A family of stations
builds ``FetchRequest(out_dir, station_ids=...)``, or the extent with the period the cache misses.
A family of grids builds the extent in ``PROJECT_EXTENT_CRS`` with its period. ``file`` and
``url`` are registered classes of the port. The base class loads file sources through
``load_file_source`` or ``load_file``, and a variable whose format takes real work overrides it or
keeps a dedicated loader. The ``source`` field is a string checked against
``data_sources.names(section)`` while the file is read, so a name this installation does not serve
is refused with the names it serves, and the JSON schema and the config reference publish the
values. ``dem``, ``geology`` and ``crossings`` keep a discriminated union, because each of their
sources carries its own model of options. ``tests/unit/data/test_variable_families.py``
ties the lists. The ``source`` values of each variable match ``data_sources.names(section)``, and
each has an entry (licence, network hosts) in ``hydromodpy/schema/sources.py``.

The folders of a family
~~~~~~~~~~~~~~~~~~~~~~~

In ``families/``, ``common.py`` holds the state shared by all variables and the ``SOURCES``
dispatch. ``stations.py`` does the API fetch, writes one chronicle per station under a lock and
handles the frozen mode. ``grids.py`` writes one NetCDF per box and period with its sidecar, and
it removes the smaller grids the new one replaces. ``files.py`` reads user files where they lie
and puts a copy under ``blobs/``, which is never a row of the cache. ``base_config.py`` holds
``BaseVariableConfig``, the date window every ``[data.<name>]`` section has, and
``timeseries_config.py`` holds the CSV column names, the station selection and the cache options
of the chronicle configs, and the two source bases of the twin variables.

Four rules hold in the bases. ``file`` is never in ``SOURCES``, because the base class loads the
user's files itself and a user file is no row of the cache. A fetched file is written beside its
name and renamed in place, then its sidecar is written through ``CacheIndex.record``. A station
chronicle is written inside ``index.chronicle(folder, stem)``, which holds the lock of that
station, and the old file of the station leaves in the same lock. A variable that downloads needs
the data folder of the call, and without one it is refused and nothing is written under the cache
of the user. A variable does not read the project geometry. The caller gives it an extent or a
mask.

The DataSource port
~~~~~~~~~~~~~~~~~~~

``source/README.md`` is the contract of the port, in full. It names the members a source class
declares, the ``FetchRequest`` (an extent and its CRS, stations, a period, or a request with none
of them for a source that selects nothing), the ``FetchResult`` and its ``FileRecord`` entries,
and the hosts a shipped source reads from ``hydromodpy.schema.sources``. Every provider is one
class of the port, so a source is found the same way whatever it serves, with
``data_sources.get(section, source_id)``, the two-part key joined by ``_``. A source's points and
fields are written in the unit their record carries, the SI is reached at the entry of the Model
through ``core/units``, and the port converts no value. A source knows nothing of the catalog, the
workspace, a lock or a cache. The variable builds the request and keeps the cache, and the source
fetches. ``source/permanence.py`` names the one canonical ``permanence`` column a source writes
when it knows whether water flows all year.

Rules between the subpackages
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A subpackage imports only the subpackages its row of ``tests/unit/architecture/data_layout.yaml``
allows, and ``tests/unit/architecture/test_package_layouts.py`` checks every import, whether it is
at module level, inside a function, under ``TYPE_CHECKING`` or a dotted path in a lazy-attribute
table. Every subpackage may import ``core``. Six more rules hold. A variable never imports another
variable. Another layer of HydroModPy imports only the modules listed under ``public`` in
``data_layout.yaml``, so the bases in ``families``, ``common`` and ``schemas`` (but the DEM
contract that the check of the input files reads), the registry and the store of ``loading`` and
the inside of the variables stay private. A variable reaches its providers through the source
registry, so adding a provider touches no variable body and an ``if`` on the source name has no
reason to appear. No module uses a ``_private`` attribute of another, and Ruff rule ``SLF001``
checks it. The modules that hold a ``DataSource`` class import geopandas, pandas, rasterio or
requests inside their functions, so looking a source up by name loads nothing heavy, and
``tests/unit/architecture/test_layers.py`` checks it, one module per source. The last rule is one
exception to the import rules. The source registry (``source/registry.py``) names the shipped
classes by a dotted path written as text and imports each on first use, so that a third-party
plugin joins the same table. The registry is ``data_sources``, an instance of the engine of
``core/plugin_registry.py``, keyed on the section and the ``source_id`` of the class.

``data`` imports ``core``, ``schema``, ``catchment``, ``mesh`` and ``model`` as
``layer_matrix.yaml`` says, and it never imports ``results``. ``config``, ``calibration``,
``workflow``, ``project``, ``cli`` and the root facade import ``data``, and ``catchment`` does
not.

How data flows
~~~~~~~~~~~~~~

During a run, ``loading/config_schema.DataConfig`` validates ``[data]``,
``loading/planner.DataPlanner.build()`` finds the asked-for and inferred variables, and
``loading/loader.DataLoader`` applies the simulation window and the basin mask. Each variable then
loads through ``variables/<v>/variable.<V>Variable.load()``, from files or from the class of the
port named by ``data_sources.get(section, source)``, and the loader collects a
``contracts.LoadResult`` with points, fields, tables and warnings. A user who loads data by hand,
outside a project, calls ``DataStore().load_variable("hydrometry", cfg)``. Without a folder,
nothing is read from or written to a cache, and ``DataStore(data_root="data/")`` takes a data
folder of your choice.

One engine, ``request/engine.run_request``, serves a ``DataRequest`` from outside a project. The
request holds ``[data]`` sections with the models of the TOML, an extent that is exactly one of a
box with its CRS, a vector mask (a file link, pinnable by ``sha256``) or station codes, an
optional period, and plugin sources under ``installed``, whose options are bound against their
constructor before anything runs. The engine writes one file per variable and source, cut to the
extent and period, beside a report ``request.json`` that lists each file with its sha256, size,
CRS, box, period and unit, and the variables that failed. The two ways in are ``hmp data get
request.json --to DIR``, or ``hmp data get <variable> --bbox ... --crs ... --to DIR``, and
``run_request(DataRequest(...), out_dir)``, which returns a ``RequestReport``.

``request/model.py`` reads the request. ``engine.py`` loads each section through its variable over
the extent, written as a polygon mask in the CRS of the variable. ``hydrography`` and the
installed sources go through the source registry, never through the Whitebox code. A source that
fails loses its files and is listed with its error, and the others keep theirs. An empty answer,
such as a box at sea, is a success marked ``"empty": true``. ``artefacts.py`` cuts each answer to
the extent and period, whatever the cache held, and writes chronicles in one Parquet table, grids
in one NetCDF, rasters in GeoTIFF, vectors in one GeoPackage layer and tables in Parquet.
``job.py`` is the ``data-request`` declaration and its body. It resolves and refuses before
anything is written, uses a data folder under the scratch of the job indexed in memory, writes the
seal, and reuses an earlier answer when the request is the same. A ``file`` or ``custom`` source
is refused, because a request has no project folder to read it from, and a failed variable fails
the job while the report of ``run_request`` lists it instead. Nothing is written to a project.
``cache_verbs.py`` holds the verbs of ``hmp data`` on the data folder, which are ``ls``, ``get``,
``remove``, ``archive``, ``restore``, and ``prune`` through ``project``, which knows what is
cited. The tests are ``tests/unit/data/request/test_engine.py`` and
``tests/unit/data/request/test_job.py``.

How a load goes
~~~~~~~~~~~~~~~

``loading/config_schema.py`` validates ``[data]`` as ``DataConfig``, and it reads each typed
section (``[data.hydrometry]``, ``[data.dem]`` and so on) with the config class that
``VARIABLE_SPECS`` names for it. ``planner.py`` (``DataPlanner``) builds the plan, which is the
variables listed in ``[data].types`` plus the ones another section implies, such as the rain and
the evapotranspiration the soil reservoir reads. The plan is an immutable ``DataLoadPlan``
(``plan.py``). ``loader.py`` (``DataLoader``) runs the plan inside a project run. For each
variable it builds the variable class from ``VARIABLE_SPECS``, gives it the extent and the period,
and collects the ``LoadResult``. ``store.py`` (``DataStore``) does the same for a user who loads
data by hand. ``inputs.py`` resolves the user files and URLs a document declares, before the run
is registered.

``VARIABLE_SPECS`` names the config and variable classes as text paths so that nothing is imported
before it is needed, and it holds the columns of the folder ``data/<variable>/`` that the
workspace scaffold writes (category, kind, unit, label). The tuple ``DATA_VARIABLES`` and the
scaffold read it and keep no list of their own, so nothing here imports a variable class at module
level. A variable still needs a field in ``DataConfig``, a field of ``LoadedDataContext`` and, for
a provider, an entry in ``schema/sources.py``.
``tests/unit/data/test_variable_families.py`` names the list you missed, and
:doc:`../how-to/add-a-data-variable` gives the full recipe.

Where the extent of a variable comes from
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A variable resolves the box it asks a provider over from the source config alone
(``resolve_source_extent`` in ``common/source_extent.py``), with ``mask_path`` first, then
``extent`` together with ``project_extent``. No variable takes a project-scoped object. During a
run, ``DataLoader`` writes the delineated watershed into ``mask_path`` before it hands the config
to the store. ``common/source_extent.py`` reads every mask. ``mask_geometry(path)`` returns the
polygon and the CRS the file declares, and it refuses a mask with no CRS. A raster mask goes
through the hull of its valid cells rather than its footprint, because a catchment mask is ``1``
on the catchment and nodata elsewhere in a rectangle. ``mask_extent(path)`` gives its box, and
``mask_extent_in(path, crs)`` the box of the reprojected shape, which is tighter than a
reprojected box and keeps a cached download a superset of the request.
``mask_geometry_wgs84(path)`` is the polygon the station variables filter with, and a mask with no
CRS is read as WGS84. ``project_extent`` is a bare tuple with no CRS of its own. The raster
variables read it in ``PROJECT_EXTENT_CRS`` (``EPSG:2154``), and the station variables in
``STATION_EXTENT_CRS`` (``EPSG:4326``).

The cache is its sidecars
~~~~~~~~~~~~~~~~~~~~~~~~~

The data folder is the cache. Next to each fetched file, ``<file>.json`` records the variable, the
source, the station or product, the extent and period, the sha256 and size, the licence and where
the file came from. There is no database. A folder that still holds a ``cache.duckdb`` of
HydroModPy 2.0.0 is refused with ``hmp workspace clean --data-cache``, which removes it.
``scan(data_root)`` walks the folder once and returns the rows, and three rules say what is a row.
A sidecar must name its ``variable``, and it is written only with one, so a sidecar without it is
listed in the report of the scan and is no row. Locks (``*.lock``), writes in progress
(``*.part``), hidden names, ``blobs/``, ``sites/`` and ``extracted_ign/`` are skipped by name, and
a ``.json`` that is not a sidecar is skipped with them. A user file is no row. Your files live
under ``inputs/``, and a sidecar with ``source = "file"`` is counted apart in the report and never
pruned.

``CacheIndex`` scans once per object, keeps the rows in memory and answers ``find`` by variable,
source, station, product, extent and period. A station chronicle is written inside
``index.chronicle(folder, stem)``, a file lock, so two cases that fetch the same station write the
same bytes in turn. A thousand sidecars scan in about 30 ms and ten thousand in 0.3 s.
``prune(data_root, keep=...)`` receives from ``project`` the digests that a run or a lockfile
cites. It never removes such a file and names it in its report, and if ``project`` cannot read the
inputs of a run, it refuses to prune. ``hydromodpy.lock`` is written from the rows, so it carries
the source and the licence of each file. A lockfile older than ``hydromodpy.lock.v2`` is refused,
and the message says to write it again with ``hmp data lock``.

A frozen run reads only what the lockfile names. ``read_locked_inputs(project_root)`` reads the
lockfile once and gives a ``LockedInputs``, and ``project`` builds it when the request is frozen.
The run hands that object, as the argument ``locked``, to the ``DataStore``, the ``CacheIndex``,
the ``FileSource`` and the ``reject_*`` functions of ``lockfile.py``. ``None`` means a run that is
not frozen. No module global holds the mode, so two runs in two threads of one process do not see
each other as frozen.

The site catalog
~~~~~~~~~~~~~~~~

A workspace declares its sites once, in ``data/sites/catalog.csv``, one ``SiteRow`` per line
(``site``, ``label``, ``gauge``, ``uri``, ``x_outlet``, ``y_outlet``, ``crs`` and ``tags``,
defined in ``hydromodpy.core.site``). ``sites/catalog.py`` is its only reader and writer, and
``hmp site add``, ``hmp site import``, ``hmp site ls`` and ``hmp site show`` go through it. A name
is declared once. An outlet closer than ``[sites] near_site_m`` of ``workspace.toml`` (default 500
m) to the outlet of a site of another name is refused, since it is most likely the same catchment
twice. ``--force`` replaces a site of the same name and accepts a close outlet, and one conflict
writes nothing. ``sites/importers.py`` holds the importers behind ``hmp site import`` (site table,
outlet layer and Hub'Eau stations), and ``single_site.py`` resolves a ``[site]`` against the site
catalog of the workspace (``match_site``, ``resolve_single_site`` and ``SiteMismatchError``).

``[site] gauge`` is the station of a catchment. A ``file`` (chronicles) or ``hubeau`` source of
``hydrometry``, ``recharge`` or ``runoff`` with no ``station_ids`` reads it, and a list that
leaves it out is refused with the name of the key (``sites/gauge.py:apply_site_gauge``). Without a
gauge, a run that loads exactly one discharge station takes that station as its gauge
(``gauge_of_run``).

The records handed upward
~~~~~~~~~~~~~~~~~~~~~~~~~

Every variable returns a ``LoadResult`` with ``points``, ``fields``, ``tables`` and ``warnings``.
A ``PointRecord`` holds ``station_id``, ``variable``, ``source``, ``unit``, ``frequency``,
``data`` (a table), ``date_start``, ``date_end``, ``location`` (a ``StationLocation``),
``is_constant``, ``file_path``, ``source_unit`` and ``quality``. A ``FieldRecord`` holds
``variable``, ``source``, ``unit``, ``data`` (an xarray dataset or a path), ``bbox``, ``crs``,
``date_start``, ``date_end``, ``frequency``, ``source_unit`` and ``metadata``. A ``TableRecord``
holds ``variable``, ``source``, ``table_id`` (a lake abacus), ``data`` (a table or a path to
Parquet), ``unit``, ``crs``, ``source_unit`` and ``metadata``.

Where to add what
~~~~~~~~~~~~~~~~~

A provider for an existing variable is a ``DataSource`` class in
``variables/<v>/apis/<provider>.py`` (or ``common/clients/`` when several variables share it), its
section and key in ``_BUILTIN_PATHS`` of ``source/registry.py``, a value the config validates
against ``data_sources.names(section)`` and an entry in ``schema/sources.py``. A plugin source,
out of tree, is a ``DataSource`` class published on the ``hydromodpy.data.source`` entry-point
group under the name ``<section>_<source_id>``, and :doc:`../how-to/add-a-data-source` gives the
recipe. A user file for a variable is declared with ``source = "file"`` and a path relative to the
project root, under ``inputs/``, as :doc:`/how-to/use-your-own-files` says, and an online file
with ``source = "url"``, a ``url`` string and an optional ``sha256`` or ``license``. A variable is
a package on the template above, or a class pair in one of the flat modules of ``variables/`` when
it is a thin family, with a field of ``DataConfig`` and a row of ``VARIABLE_SPECS``, as
:doc:`../how-to/add-a-data-variable` says. A user-file format goes in ``ingest/``, and an import
rule in ``tests/unit/architecture/data_layout.yaml``.

A reader new to the package can start with ``variables/hydrometry/`` for a station variable and
``families/stations.py`` for how it calls the cache, then ``variables/sim2_series.py`` for a grid
variable and ``common/clients/sim2_products.py`` for SIM2. ``loading/loader.py`` shows what a run
loads and ``loading/planner.py`` the inference rules. ``request/engine.py`` serves a request from
outside, and ``provenance/sidecars.py`` holds the cache. The public symbols other layers read are
``DataConfig``, ``DataPlanner``, ``DataLoadPlan``, ``DataLoader`` and ``DataStore`` of
``loading/``, ``DataRequest`` and ``run_request`` of ``request/``, ``CacheIndex``, ``CacheRow``,
``Sidecar``, ``scan`` and ``prune`` of ``provenance/sidecars.py``, ``LoadResult`` and the three
records of ``contracts/``, the names of ``source/port.py`` and ``source/registry.py``,
``DATA_REQUEST`` and ``run`` of ``request/job.py``, and ``read_catalog``, ``write_catalog``,
``nearest_site``, ``add_sites``, ``declare_sites``, ``SITE_CATALOG_RELPATH``, ``apply_site_gauge``
and ``gauge_of_run`` of ``sites/``. The source classes themselves are imported from the module of
their provider, for example ``hydromodpy.data.variables.hydrography.apis.bdtopage``.

The variable packages
~~~~~~~~~~~~~~~~~~~~~

The digital elevation model, ``variables/dem/``, comes from the IGN Geoplateforme, from a local
file, or from the French departments that a region names. The variable returns a ``LoadResult`` of
``FieldRecord`` objects that point to cached GeoTIFF files. Before the variable runs,
``resolver.py`` resolves the first usable source into a ``FileRecord`` (path, sha256, state,
nodata, origin) that the geographic pipeline reads. The resolver must not need the cache rows, and
it still needs the data folder to download into. ``source = "file"`` reads a ``.tif``, ``.tiff``,
``.asc`` or ``.nc`` file, or a folder holding one (``custom.py``). A file without a CRS is
refused. The file is read where it lies and is no row of the cache, and a copy made from it goes
under ``data/blobs/dem/file/``. A ``file`` or ``url`` source takes ``state = "raw"`` (the default)
or ``state = "conditioned"``. ``raw`` means HydroModPy conditions the DEM itself. ``conditioned``
means another tool filled or breached it, so HydroModPy skips its own conditioning and still
computes the D8 directions and the accumulation. An API source has no ``state`` key, because a
provider delivers a raw DEM. ``source = "ign_geoplateforme_dem"`` downloads from the
Geoplateforme. With ``dataset = "bd-alti"`` (the default, 25 m) the variable builds the DEM from
the archives of the departments that the study area touches. ``apis/ign_dem_fr.py`` finds them,
``apis/geoplateforme_download.py`` downloads and extracts them, and
``apis/_bdalti_archive_index.py`` indexes the BD ALTI archives. The departments come from
``hydromodpy/catchment/administrative``, which is imported inside the functions that use it so
that geopandas loads only for a French source. With ``dataset = "rge-alti"`` (5 m by default, 1 m
allowed) it builds the DEM from WMS-Raster tiles (``apis/geoplateforme_wms.py``). The class of the
DataSource port registered under ``(dem, ign_geoplateforme_dem)`` in ``apis/ign_dem_fr.py``
downloads all three datasets, and the variable gives it the data folder and writes the sidecar of
the file it returns. The cache is indexed by box, with no time dimension.

The geology variable, ``variables/geology/``, is the geological map as polygons or as a raster of
zone codes, from the BRGM or from a file of the user, and its records point to cached GeoPackage
or GeoTIFF files. The variable does not build the geology field. ``loading/loader.py`` takes the
loaded data, rasterizes it on the domain grid and calls ``field.py``, which keeps the variable
free of the project geometry. ``source = "file"`` reads a vector (``.shp``, ``.gpkg``,
``.geojson``, ``.json``), a raster (``.tif``, ``.tiff``) or a CSV, clipped to the box
(``custom.py``), and a file in another CRS is clipped in its own CRS. The file is read where it
lies and is no row of the cache, and the clipped copy goes under ``data/blobs/geology/file/``.
``source = "brgm_1m"`` builds a GeoPackage from the 1:1 000 000 national map
(``apis/brgm_1m.py``), and ``source = "brgm_50k"`` builds one from the 1:50 000 maps of the
departments that the box touches (``apis/brgm_50k.py``). Both are classes of the DataSource port
registered under ``(geology, brgm_1m)`` and ``(geology, brgm_50k)``. The variable looks for a row
of the cache first, writes the sidecar of a download, and drops the smaller maps that the new one
contains. ``apis/fgeol.py`` holds what the two downloads share, which is the hash of a box and the
lookup of the shapefile in an archive. The two BRGM cache files are named with a hash of the box
rounded to two decimals, so a change of rounding renames every cached file. ``io.py`` reads a
source into one contract, an integer grid of codes (``0`` is nodata), a mapping from code to zone
name, a transform and a CRS. ``processing.py`` holds the small steps it needs, which are zone-key
normalization, the encoding of a numeric raster and the land-sea override.

The hydrography variable, ``variables/hydrography/``, is the river network, from BD TOPAGE,
EU-Hydro, OpenStreetMap or a file of the user. It clips the network to the extent, rasterizes it
and returns a ``LoadResult``. ``file`` reads a vector or a raster network from a file or a folder
(``custom.py``). ``bdtopage``, ``euhydro`` and ``osm`` are ``DataSource`` classes in ``apis/``
that share one shape (``apis/features.py``), a feature table over a box in WGS84, with no time
axis and nothing written under the request folder. A subclass names its source and hosts, checks
its own options, and says how to download a box. No module of this folder holds the list of names,
because ``source/registry.py`` resolves them. ``api_source.py`` turns one
``[[data.hydrography.sources]]`` entry into a network, and the variable and the resolver both call
it. A source knows nothing of the data cache. The variable owns the superset lookup, the sidecar
of a download, the clip to the mask and the rasterization of a field. What the source reports it
was asked, such as the BD TOPAGE layer or the OSM waterway types, is written in the sidecar, and a
row recorded for another question is a miss. A BD TOPAGE network carries a permanence column, and
the variable writes the permanent reaches as a separate vector, the reference of the permanent
network (``source/permanence.py``). That copy has no sidecar, so it is no row of the cache.
``resolver.py`` gives the path of the network map that a diagnostic reads, before any variable
runs, and it imports no variable. It reaches a download through ``api_source.py``.

The hydrometry variable, ``variables/hydrometry/``, loads river discharge or stage time series
from custom CSV files or from the Hub'Eau API (``apis/hubeau.py``). ``catchment_area_check.py``
compares the drainage area of a station with the catchment of the model. The piezometry variable,
``variables/piezometry/``, loads groundwater level time series from custom CSV files or from the
Hub'Eau API, with the ``level`` and ``depth`` products. In both, ``variable.py`` dispatches to the
configured source, and ``config.py`` holds the two config models with ``extra="forbid"``.

Tests
~~~~~

The unit tests mirror the code under ``tests/unit/data/``, and the tests of the variables are in
``tests/unit/data/variables/``. ``tests/unit/data/variables/geology/test_io.py``
writes small files in a temporary folder and needs no network.

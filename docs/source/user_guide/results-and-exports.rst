Results and exports
===================

**Where are my outputs?** Inside the project, in ``runs/<name>/``. One
directory per run, named after the run. Nothing is hidden in a database,
nothing is packed into an archive: the arrays are Zarr, the tables are
Parquet, the frozen configuration is TOML, the seal and the provenance are
JSON.

The DuckDB file in ``.hmp/`` is an index over those directories. It makes
listing, filtering and ranking fast. It is not the source of truth: delete
it and ``hmp catalog reindex`` rebuilds it from the run directories.

.. figure:: /_static/concepts/results/workspace_results_exports.svg
   :alt: Run directory as the source of truth, with the index rebuilt from it
   :width: 100%

   The run directory holds everything a reader needs. The index answers
   "which runs exist"; ``hmp catalog reindex`` rebuilds it from the seals.

What one run writes
-------------------

.. code-block:: text

   <project>/
   ├── project.toml                  shared settings, and the marker of the project root
   ├── run_demo.toml                 the config you launched
   ├── hydromodpy.lock               frozen input data
   ├── runs/
   │   └── nancon_intermittence_mf6/
   │       ├── config.toml           frozen resolved configuration of this run
   │       ├── fields.zarr/          array store: head, mesh, forcings, derived
   │       ├── tables.parquet/       one Parquet file per tabular payload
   │       ├── figures/              figures rendered for this run
   │       ├── manifest.json         seal, written last
   │       ├── provenance.json       versions, git commit, solver binary
   │       ├── annotations.json      tags and notes, written after the seal
   │       ├── ro-crate-metadata.json, stac-item.json, prov.jsonld
   │       │                         generated views, on request, after the seal
   │       └── trash.json            present only while the run sits in the trash
   ├── sessions/
   │   └── 20260726-104019-optuna-5ecea3e0/
   │       ├── session.json          identity, search space, best trial
   │       └── trials.jsonl          one JSON line per evaluated trial
   ├── share/                        on-demand exports, reports, .hmp packages
   └── .hmp/                         internals: index.duckdb, logs, checkpoints, scratch

Two rules follow from that layout:

- **A run directory without a manifest did not finish.** ``manifest.json``
  is written last, after every artefact it declares.
- **A run keeps its name.** ``runs/<name>/`` is the human name of the run,
  with its ``.vN`` suffix when the name was reused
  (``aber_transient_mf6.v2``). ``hmp catalog rename`` moves the directory,
  then updates the index.

Reading each artefact
---------------------

``tables.parquet/`` with pandas
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Plain Parquet files. No HydroModPy import needed.

.. code-block:: python

   import pandas as pd

   tables = "runs/nancon_intermittence_mf6/tables.parquet"
   metrics = pd.read_parquet(f"{tables}/metrics.parquet")
   budgets = pd.read_parquet(f"{tables}/budgets.parquet")
   series = pd.read_parquet(f"{tables}/timeseries.parquet")

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - File
     - Columns
   * - ``simulation.parquet``
     - One row: the run snapshot the index rebuild reads back.
   * - ``metrics.parquet``
     - ``sim_id``, ``station_id``, ``variable``, ``metric``, ``value``,
       ``n_samples``, ``valid_from``, ``period_start``, ``period_end``.
   * - ``parameters.parquet``
     - Parameter name, zone, value, unit, parameterization.
   * - ``timeseries.parquet``
     - ``sim_id``, ``station_id``, ``variable``, ``component``,
       ``timestep``, ``time``, ``value``, ``unit``, ``qflag``.
   * - ``budgets.parquet``
     - ``sim_id``, ``timestep``, ``zone_id``, ``component``, ``flux_in``,
       ``flux_out``, ``unit``.
   * - ``mass_balance.parquet``
     - ``sim_id``, ``timestep``, ``quantity``, ``total_in``, ``total_out``,
       ``storage_in``, ``storage_out``, ``percent_error``, ``unit``.
   * - ``provenance.parquet``
     - One row per input artefact used by the run.
   * - ``geographic_<name>.parquet``
     - GeoParquet features: watershed, contour, buffered box, hydrographic
       networks.

``fields.zarr/`` with xarray
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The array store keeps ``head``, ``time`` and ``crs`` at the root, and groups
the rest: ``mesh``, ``geographic``, ``forcing``, ``derived``, ``state``,
``particles``, ``meta``.

Read it through :func:`hydromodpy.read`, which resolves the variable name
against the field registry and hands back a lazy ``xarray.DataArray``:

.. code-block:: python

   import hydromodpy as hmp

   catalog = hmp.open("~/ws/projects/my_basin")
   run = catalog.latest()

   head = hmp.read(run, "head")                 # lazy DataArray (time, layer, cell)
   last = hmp.read(run, "head", time=-1, layer=0)  # eager numpy array

Passing ``time`` as an ``int`` returns the eager ``numpy`` array of that
single step; leaving it out loads every persisted step lazily. ``sel`` and
``bbox`` narrow the read further.

The store carries no ``dimension_names`` metadata, so ``xarray.open_zarr``
on the directory raises. For raw access, open the group with ``zarr``:

.. code-block:: python

   import zarr

   store = zarr.open_group("runs/nancon_intermittence_mf6/fields.zarr", mode="r")
   print(store.tree())

Derived fields are rebuilt at read time
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The store persists primary variables. Six fields are **not** stored: they
are recomputed on every read, from the head, the per-cell budget and the
mesh.

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - Field
     - Rebuilt from
   * - ``watertable_elevation``
     - head at the uppermost saturated layer.
   * - ``watertable_depth``
     - ``topography - watertable_elevation``, clipped at zero.
   * - ``seepage_mask``
     - the surface-excess budget field when the solver writes one,
       otherwise the geometric criterion on the water table.
   * - ``outflow_drain``
     - the per-cell drain budget field, summed over layers, sign-corrected
       to a positive outflow. Needs the spatial budget to be persisted.
   * - ``release_flux``
     - every budget term that carries water out of the aquifer (drain and
       DRN-TO-MVR, SFR streams, LAK lakes, surface excess), each made a
       positive outflow and summed per cell, in m3/s. Asking for it with
       ``[simulation.results.derived] release_flux = true`` keeps those terms
       in the store.
   * - ``fluxes_from_budget``
     - the drain budget field (the recharge one when there is no drain),
       summed over layers and divided by the cell area, in m/s. Needs the
       spatial budget to be persisted.

They read exactly like a stored field:

.. code-block:: python

   water_table = hmp.read(run, "watertable_elevation", time=-1)

Because they are computed, they load eagerly and ignore laziness. That is
also why a run with no persisted budget still exposes
``watertable_elevation``, ``watertable_depth`` and ``seepage_mask``, but not
``outflow_drain`` or ``fluxes_from_budget``. A run written before
``release_flux`` and ``fluxes_from_budget`` were rebuilt on read still holds
them under ``derived/``, and the stored array is what a read returns.

Stored precision
~~~~~~~~~~~~~~~~

The time-varying fields (head, per-cell budget terms, stored derived fields,
concentrations) are float32 with their mantissa rounded to 16 bits, set by
``[simulation.results.persistence] field_precision = "compact"``. Each value
moves by at most 2**-17 of itself, 7.6e-6 relative: 1 mm on a 130 m head.
The store is about three times smaller than in float64. Such an array carries
the CF attributes ``quantization = "quantization_info"`` and
``quantization_nsb = 16``. ``field_precision = "exact"`` keeps float64. Mesh
geometry, topography, thicknesses, indices, coordinates and timestamps are
never rounded. :func:`hydromodpy.read` and every reader of the library hand
back float64 either way; raw ``zarr`` access sees the stored float32.

``manifest.json``, ``provenance.json``, ``annotations.json``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Three small JSON files, readable with ``json.load``.

- ``manifest.json``: ``manifest_version``, ``sealed_at``, ``run`` (id, name,
  version, status, project), ``geometry`` (cells, layers, mesh topology,
  mesh hash, CRS, bbox), ``period``, ``config`` (file and hash),
  ``artifacts[]`` (every declared file with its role, format and size),
  ``parameters``, ``metrics``.
- ``provenance.json``: ``tool``, ``git`` (commit, dirty flag), ``python``,
  ``platform``, ``packages``, ``environment`` (frozen package list),
  ``solver`` (name, version, binary path, binary SHA-256), ``timing``.
- ``annotations.json``: ``tags`` and ``notes``. Written after the seal, so
  tagging a run never invalidates its manifest.

``config.toml``
~~~~~~~~~~~~~~~

The resolved configuration of that run, after the ``base_config`` chain,
the overlays and the ``--set`` overrides. It is what ``hmp catalog rerun``
replays and what ``hmp run --resume`` reads back.

Reading from the command line
-----------------------------

.. code-block:: bash

   hmp catalog ls                        # every run of the project
   hmp catalog ls --status completed --solver modflow6
   hmp catalog show <ref>                # metadata, metrics, parameters
   hmp catalog show <ref> --detail       # plus the Zarr store layout
   hmp catalog diff <ref_a> <ref_b>      # only the keys that differ
   hmp catalog query "SELECT name, solver, status FROM v_simulation_summary"
   hmp report compare <ref_a> <ref_b>    # side-by-side metric table
   hmp viz show <ref> <figure>           # render into runs/<name>/figures/

A reference is a run name, a versioned name (``aber_transient_mf6.v2``), a
unique id prefix, the full id, or a selector such as ``@last`` or
``@best:nse``. Inspection commands open the index read-only.

``hmp catalog query`` runs SQL against the index. ``simulations`` stores
foreign keys (``solver_id``, ``status_id``); ``v_simulation_summary``
resolves them into readable columns, so query the view unless you need the
raw table.

Reading from Python
-------------------

.. code-block:: python

   import hydromodpy as hmp

   catalog = hmp.open("~/ws/projects/my_basin")
   run = catalog.latest()

   run.name, run.solver, run.status
   run.summary()                # identity, cells, layers, timesteps, duration
   run.parameters               # DataFrame indexed by parameter name
   run.metrics                  # DataFrame: station_id, metric_name, value
   run.mass_balance             # DataFrame
   run.budget()                 # DataFrame
   run.timeseries("discharge")  # pandas Series indexed by time

Resolve a reference, then index the catalog:

.. code-block:: python

   sim_id = catalog.resolve("ab12")
   run = catalog[sim_id]

List and filter:

.. code-block:: python

   frame = catalog.list_simulations(status="completed")
   runs = catalog.find(solver="modflow6")

Cross-run SQL:

.. code-block:: python

   ranking = catalog.sql(
       """
       SELECT name, solver, status, duration_s
         FROM v_simulation_summary
        ORDER BY created_at DESC
       """
   )

Time series and geographic features go through the same
:func:`hydromodpy.read` door:

.. code-block:: python

   q = hmp.read(run, "discharge", sel={"station": "_catchment"})  # pandas Series
   watershed = hmp.read(run, "watershed")                         # GeoDataFrame

Exports a run writes itself
---------------------------

Each ``[[export]]`` block of the run config is one request, written at the end
of the run in the order of the file. A block says what (``variables``), when
(``time`` or ``period``) and where (``folder`` or ``file``). Only ``variables``
is required; the format follows the data.

.. code-block:: toml

   # The water table in the driest month: one GeoTIFF per variable.
   [[export]]
   variables = ["head", "watertable_depth"]
   time = "2002-10-15"

   # The record of the water table: one NetCDF.
   [[export]]
   variables = ["head", "watertable_depth"]
   file = "water_table_2000_2002.nc"

   # The catchment and the mapped network: one GeoPackage each.
   [[export]]
   variables = ["watershed", "hydrographic_network_reference"]

   # Gauged and simulated discharge over two years: CSV.
   [[export]]
   variables = ["discharge", "discharge_obs"]
   period = ["2001-01-01", "2002-12-31"]

   # The portable archive of the run.
   [[export]]
   variables = "all"
   format = "package"

.. list-table::
   :header-rows: 1
   :widths: 30 35 35

   * - Data
     - One date
     - Several dates, a period, or the whole run
   * - Mesh field (``head``, ``watertable_depth``, ``seepage_mask``...)
     - GeoTIFF, one file per variable
     - NetCDF, one file for every field of the block
   * - Series (``discharge``, ``discharge_obs``...), table ``budget``
     - CSV
     - CSV
   * - Vector layer (``watershed``, ``hydrographic_network_reference``...)
     - GeoPackage
     - GeoPackage
   * - Raster layer (``watershed_dem``, ``watershed_fill``)
     - GeoTIFF
     - GeoTIFF

- ``time`` takes a date, ``"first"``, ``"last"`` or a list of them. A date
  takes the stress period that holds it, so one date names the same month on a
  monthly and on a daily run. ``period`` takes two dates.
- ``format`` forces a format: ``netcdf``, ``geotiff``, ``csv``,
  ``geopackage``, ``shapefile``, ``vtu``. A format that holds one instant
  (GeoTIFF, Shapefile, GeoPackage, VTU) writes one file per date.
  ``package``, ``stac``, ``rocrate`` and ``prov`` describe the whole run and
  take ``variables = "all"`` only.
- ``folder`` defaults to ``share/<run>/``; a relative folder is read from
  ``share/``. ``file`` names one exact file inside the folder, and its
  extension gives the format.
- ``crs`` reprojects a raster or a vector layer; NetCDF, VTU and CSV refuse it.
  ``resolution`` sizes the pixels of a GeoTIFF of a field.

``hmp config check`` refuses a block before any solve: a name no run can
export, a date outside ``[simulation.time]``, ``time`` with ``period``, a
``file`` on a request that writes several files, a format a data cannot take,
two blocks writing one file. Each refusal names its block, ``export[2]``.
A file written for the older ``[export]`` table of format toggles still loads;
``hmp doctor --fix-config`` rewrites it as ``[[export]]`` blocks.

Exporting a finished run
------------------------

The same words work after the run, from Python and from the command line.
:func:`hydromodpy.export` and ``run.export`` take the keys of a block as
arguments and return the files they wrote.

.. code-block:: python

   run.export("all")
   run.export(["head", "watertable_depth"], time="2002-10-15")
   run.export(["discharge", "discharge_obs"], period=("2001-01-01", "2002-12-31"))
   run.export("watertable_depth", time="last", file="depth_wgs84.tif", crs="EPSG:4326")
   hmp.export(run, "all", format="package")

.. code-block:: bash

   hmp export <run> --list
   hmp export <run> all
   hmp export <run> head watertable_depth --time 2002-10-15
   hmp export <run> discharge discharge_obs --period 2001-01-01 2002-12-31
   hmp export <run> watershed hydrographic_network_reference
   hmp export <run> watertable_depth --time last --file depth_wgs84.tif --crs EPSG:4326
   hmp export <run> all --format package

``--list`` prints what this run can export, grouped by kind: fields, series,
vector layers, raster layers, tables. Two runs rarely hold the same names:
``[simulation.results]`` decides what each one persists. ``hmp export``
prints the path of each file it writes, one per line; ``-w`` names the
project when it is not the current directory.

What each file holds:

.. list-table::
   :header-rows: 1
   :widths: 16 16 68

   * - Format
     - Suffix
     - Notes
   * - CSV
     - ``.csv``
     - Series: ``datetime, station_id, variable, value, unit``. Times are the
       run's clock, naive, ``2002-10-01 00:00:00``. The simulated catchment
       series is the station ``catchment``. Observations are clipped to the
       simulated window, or to ``period``. The budget has one row per period,
       zone and component, with ``period_start`` and ``period_end``.
   * - NetCDF
     - ``.nc``
     - NetCDF-4 with a UGRID-1.0 mesh, every field of the request, the dates
       asked for. Carries the ACDD metadata of the run. Opens in QGIS as a
       mesh layer; see the note below.
   * - GeoTIFF
     - ``.tif``
     - Cloud-optimised raster. The pixel size follows the mesh unless
       ``resolution`` is given. Tags name the run, the variable, its units
       and the period (``HMP_PERIOD``).
   * - GeoPackage
     - ``.gpkg``
     - A vector layer as stored, or one polygon per cell carrying a field.
   * - Shapefile
     - ``.shp``
     - The same, for software that reads nothing else.
   * - VTU
     - ``.vtu``
     - Mesh plus field, every layer, for ParaView.
   * - ``.hmp``
     - ``.hmp``
     - Portable package: config, provenance, fields, tables, manifest.

A file of one instant is named by the date asked (``head_2002-10-15.tif``),
or by its period when the request names none (``head_2002-10.tif`` on a
monthly run). A NetCDF holding several fields is ``<run>_fields.nc``.

A field of several layers in a format of one layer (GeoTIFF, GeoPackage,
Shapefile) needs ``layer``: the top layer of a multi-layer model can be dry.
``watertable_elevation``, ``watertable_depth`` and ``seepage_mask`` hold one
value per cell and never need it. NetCDF and VTU keep every layer.

``simulated_active_network`` is the stream network the model simulates: 1 on
the cells the network criterion counts as flowing at that date, 0 elsewhere,
cut with the settings of the run's calibration output (the criterion's
defaults when it sealed none). It is a field like the others: a GeoTIFF or a
GeoPackage at a date, a NetCDF over the run. It needs the run's
``release_flux`` and a stored hydrographic network.

``stac``, ``rocrate`` and ``prov`` are generated views of the run itself,
rendered from the seal: without ``folder`` or ``file`` they are written
inside the run directory, beside ``manifest.json``, where the paths they name
resolve.

Opening a NetCDF export in QGIS
-------------------------------

Add the ``.nc`` as a **mesh** layer, not a raster or a vector one: QGIS reads
it through MDAL, which understands the UGRID topology the file carries. Each
field becomes one dataset group with its own time steps, and the layer comes
georeferenced, so it lands on the catchment rather than in the project CRS.

MDAL binds a dataset to the mesh faces and nothing else, so a field stored per
layer is written one variable per layer: ``head`` on a single-layer model,
``head_layer1`` and ``head_layer2`` above it. Reading the file back with
``hmp`` puts the layers together again.

Re-exporting over a file a QGIS layer still has open is safe, but QGIS keeps
showing the version it opened: reload the layer to see the new one.

Packaging a run for exchange
----------------------------

.. code-block:: bash

   hmp export <ref> all --format package --file paper_run.hmp
   hmp catalog import share/<ref>/paper_run.hmp

.. code-block:: python

   run.export("all", format="package", file="paper_run.hmp")
   catalog.import_package("share/<ref>/paper_run.hmp")

The archive carries the frozen config, the provenance, the fields and the
tables, with checksums verified on import. The run identity survives the
round-trip, so re-importing into the same project is refused unless
``--force`` is given.

Rebuilding the index
--------------------

.. code-block:: bash

   hmp catalog reindex

The rebuild walks ``runs/`` and ``sessions/``, reads each ``manifest.json``
and each ``session.json``, and repopulates the index. It reports what it
found:

.. code-block:: text

   indexed 3 run(s) and 1 session(s)
     baseline_run
     nancon_calibrated
     nancon_calibrated_trial_0016
     20260726-104019-optuna-5ecea3e0
     calibration_iterations: 20 row(s)
     calibration_sessions: 1 row(s)
     ...

Use it after moving a project, after restoring a backup, or whenever the
index and the disk disagree. Deleting ``.hmp/index.duckdb`` loses nothing
that a rebuild cannot restore.

Temporal conventions in comparison CSV exports
----------------------------------------------

Comparison CSV files distinguish state snapshots from period values
explicitly. Read the ``time_role`` column before interpreting
``time_index`` or ``elapsed_seconds``.

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - ``time_role``
     - Meaning
   * - ``initial_state``
     - Explicit state before the first transient period. Useful for
       initial-condition diagnostics, but it is not a budget period.
   * - ``state_snapshot``
     - Instantaneous model state at the reported elapsed time, for example
       a hydraulic-head or water-table map.
   * - ``period_value``
     - Value associated with a completed period. Budget tables also provide
       ``period_index``, ``period_start_seconds`` and
       ``period_end_seconds``.
   * - ``reduced``
     - Row obtained by reducing several time rows, for example with a mean,
       min, max or sum reducer.

For budgets, ``elapsed_seconds`` is the period end time. Do not compare a
``period_value`` row to an ``initial_state`` row. Boussinesq histories may
store an explicit initial state at ``t = 0``; comparison budget exports skip
that row instead of treating it as a zero-duration budget.

Comparison metrics enforce the same distinction: fallback matching can align
equivalent elapsed times or equivalent non-initial order positions, but it
must not compare rows with different ``time_role`` values. For explicit
state selection, prefer ``time = "initial_state"`` when the initial
condition itself is the target, and ``time = "first_computed"`` when the
first transient result is the target. The legacy ``time = "first"`` selector
means "first available row" and is therefore ambiguous when one solver
exports an initial state and another starts at the first computed step.

Where to look next
------------------

- :doc:`concepts/workspace-layout` for the workspace, project and run
  hierarchy and the path-resolution rules.
- :doc:`/cli/index` for every command and its flags.
- :doc:`/architecture/storage-layout` for the storage contract itself.
- :doc:`/api/index` for the low-level classes and methods.

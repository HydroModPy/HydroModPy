Package: results
================

.. include:: ../../../../../hydromodpy/results/README.md
   :parser: myst_parser.sphinx_
   :start-line: 1

Modules
-------

.. hmp-module-table:: results

Inside the package
------------------

The folders
~~~~~~~~~~~

``storage/`` holds the layout contract and the seal order, ``record/`` the seal of a run and
its value digests, ``catalog/`` the index and its reader, ``run/`` the ``Run`` view,
``session/`` the formats of a calibration session, ``zarr_store/`` the arrays of one run,
``derive/`` what is computed at read time, and ``export/`` and ``exporters/`` the files that
leave a run. The sections below say how the work flows in each folder and where to add what.

The plan of a project is ``plan.json``, ``cases.csv`` and one TOML per case under
``plan/<hash>/``, written once by ``plan_store.py`` and read back by ``read_plan``, whose
``sites`` is a table of text. ``retention.py`` weighs a project by family, and ``Project.gc()``
or ``hmp catalog gc`` removes what its policy allows and reports the bytes before and after.

An attempt writes two logs, ``<run>/logs/run.log`` and ``<project>/.hmp/logs/hydromodpy_debug.log``,
and neither is a handler of the package logger. ``core/logging.py`` keeps one router on that
logger, and the router sends each record to the files listed in the context variable
``RUN_SINKS``. So two runs in two threads of one process fill two ``run.log`` files and no line
crosses. The project log rotates at 8 MiB and keeps three old files. A thread pool of a run
submits its tasks through ``contextvars.copy_context().run``, so a task keeps the files of the
thread that started it.

Storage and the seal
~~~~~~~~~~~~~~~~~~~~

``storage/contract.py`` is the place to look for a name. ``CERTIFIED_RUN_ENTRIES`` lists what
the seal inventories, and ``UNSEALED_RUN_ENTRIES`` what it never does, which is derived,
mutable, diagnostic or machine state. A new file enters ``contract.py`` first, then
``tests/unit/results/test_run_layout_contract.py``.

The seal is written in one order. First come the CRS in WKT2, the attributes of ``fields.zarr``
from the ``Identity``, the value digests, the copy of the sealed mesh, the class of a replay
and the record of the run. Then ``README.md`` follows, and its section "What this run does not
give" is read from the keys of the digests, which are the keys of what the run stored. A run
that reads a product of the store copies the mesh under ``mesh/`` when its engine caches one.
``final_state/`` holds the last head and stages in float64, which a restart and the next
window read before the last step of ``fields.zarr``. ``profile.json`` sits outside the seal and
the identity, because it describes one machine.

``kept.py`` gives the level of a run and what that level keeps. A kept calibration trial is a
research run, keeps no figure and no export, and leaves ``purged.json`` when ``gc`` removes
fields older than its policy, a file outside the seal like the outcome. ``declared.py`` holds
what a backend may write. A field or table that its ``writes`` does not declare, and a
simulated series that the registry does not describe, are refused.

The record
~~~~~~~~~~

``record/`` holds the record of one run, which is the seal it writes, the value digests and the
class of a replay. ``manifest.json`` closes the run at ``manifest_version`` 4 and
``profile = "run"``, on the common seal of ``hydromodpy/schema/seal.py``, and the seal of a job
is the other profile of that document. A seal weighs 24 to 36 kB on the frozen runs of the
references, of which 14 to 19 kB are value digests, one per Zarr array and per column of a
quantity, taken under the rule ``values/1``. A field rounded for storage is hashed in double
precision before the rounding of 2^-17, so ``bit`` covers the values as computed. A seal of the
2.0.0 reads through ``forms.py``, in memory and never rewritten, and a seal of a pre-release is
refused with its sentence. A replay compares its digests with the seal of its source and writes
``bit`` or ``deviation``, with ``max_abs`` and ``rel_l2`` of the whole field for each key that
differs. ``figures/``, ``exports/`` and ``report/`` are written after the seal and never
inventoried (``list_artifacts`` of ``manifest.py``). The folder reads ``core``, ``schema`` and
``results``, and nothing above ``results``.

The catalog
~~~~~~~~~~~

``catalog/`` answers how the runs of a project are found, ranked and compared. The index
``.hmp/index.duckdb`` is derived from the run and session directories and can be rebuilt at
any time. ``Catalog`` reads it and nothing more. The indexer is the only writer, and
``Catalog`` builds the index when it is missing or comes from another build, then reads it.

1. ``registration.py`` reserves the name of a run directory (``reserve_version_dirname``) and
   computes the identity hashes of a configuration.
2. The indexer (``indexer.py``) takes the lock ``.hmp/index.duckdb.lock``, which is a lease of
   600 s renewed every 100 entries with a wait of 120 s. It reads every run, session and kept
   trial into a staging file opened by ``index_file.py``, checks that it still holds the lock,
   and publishes that file in one rename. A pass with nothing to do takes no lock.
   ``rebuild_index`` does the whole tree and ``index_new_runs`` does a diff.
3. ``index_schema.py`` is the DDL of the index, and a change of schema is a full rebuild.
   ``views.py`` adds the summary views. ``index_file.py`` is the only opener of the index file,
   in blocks of 16 KiB.
4. ``Catalog`` (``facade.py``) opens the index read-only through ``DuckDBBackend``, the one
   backend, in ``adapters/duckdb.py``.
5. ``discovery.py`` turns a reference (a name, an id, ``@last``, ``@best:METRIC``) into a run,
   and ``reads.py`` holds the queries.
6. ``catalog[ref]`` gives a ``Run``. ``Catalog.query_timeseries``, ``query_budget`` and
   ``query_mass_balance`` delegate to the ``Run``. ``read_geographic_feature``,
   ``list_geographic_features`` and ``read_geographic_metadata`` read the run directory and not
   the index.
7. ``listing.py`` holds the reads behind ``hmp ls``, ``show``, ``query``, ``point``, ``diff``
   and ``rank``. ``liveness.py`` and ``privacy.py`` read the directories and never open the
   index, so ``hmp catalog watch``, ``hmp doctor`` and the purge of a run answer while the index
   is being rebuilt.

``constants.py`` holds ``SIMULATIONS_FROM``, the one join of a run row to the codes of its
solver, status, flow regime and mesh topology, and every reader of a run row uses it.
``federation.py`` reads the sealed runs of several projects with no index, ``parquet_views.py``
holds the DuckDB views over the Parquet tables of a run, ``dataset_loader.py`` makes a
catalog-wide dataset for model training, and ``storage_paths.py`` gives the paths of the
artifacts of a run.

To add an index table or column, change ``index_schema.py``, its read-back in ``indexer.py``
and the schema version. A summary view goes in ``views.py`` and a query of the index in
``reads.py``. A form of reference goes in ``discovery.py``. A run row read with its codes
starts from ``SIMULATIONS_FROM``. Another database engine is a backend beside
``adapters/duckdb.py``, with ``Catalog`` typed on what both share. A read across projects goes
in ``federation.py``, a listing of runs for a command in ``listing.py``, and a read of running
attempts that must not need the index in ``liveness.py``.

The run view
~~~~~~~~~~~~

``run/`` answers how one finished simulation, or a set of them, is read back. ``Run`` is one
run directory and ``RunSet`` a view over several runs. The rows of a run (series, budgets,
parameters) come from its own Parquet files and its arrays from its own Zarr store. The index
is only used to find the run.

1. ``Catalog`` resolves a reference and hands back a ``Run``. A run still being computed is
   opened on its ``RunStore``, and a sealed directory is opened with ``open_run_dir``.
2. ``Run`` (``view.py``) loads the row that describes the run on first use, from the index or
   from the facts of the directory.
3. Its tabular reads go to ``tables.py``, which reads the Parquet tables of the directory
   (``read_run_table``).
4. Its mixins add the rest. ``geographic.py`` serves features, rasters, grid, mesh and field
   reads. ``timeseries.py`` serves parameters, metrics, budgets, series and the time index.
   ``hydrographic.py`` serves the network roles.
5. Providers hang on the run. ``run.array`` is the xarray reader, ``run.probe`` reads one
   place, ``run.periods`` places the stress periods on the calendar and ``run.descent`` gives
   the routing descent, with the open water, the outline cells and the mean recharge that the
   stream criterion reads. ``read_basin`` and ``basin_of_group`` return the stored basin as a
   ``StoredBasin``, for the run views and the catchment aggregation alike.
6. ``sealed.py`` reads what the seal says about the run, such as its lineage, inputs, label
   and metrics.
7. ``RunSet`` (``group.py``) ranks and compares runs, using ``ranking.py`` and the facts of
   ``sealed_facts.py``.

The other modules are ``point.py`` (one cell, one variable, one series), ``particles.py``
(pathlines), ``mesh_families.py`` (line families of the mesh), ``observation_points.py``
(declared points sampled and kept on disk), ``sfr.py`` (links between SFR reaches),
``field_envelope.py`` (min and max per cell of an earlier run), ``lake_abacus_view.py`` (the
persisted lake abacus), ``contracts.py`` (the typed returns ``Mesh``, ``RasterField`` and
``Stack``) and ``environment.py`` (the host environment snapshot).

To add a ``Run`` accessor, write a provider in this folder and bind it in ``view.py``. A
tabular read goes in ``timeseries.py`` on top of ``tables.py``, a geographic or mesh read in
``geographic.py``, something the seal states in ``sealed.py``, a column of a table of runs in
``sealed_facts.py``, and a way of ranking runs in ``ranking.py`` and ``rank_key`` of
``group.py``. A typed return for a field or a mesh goes in ``contracts.py``.

The session
~~~~~~~~~~~

``session/`` answers what a calibration session leaves on disk in ``sessions/<case>/`` and how
it is read back. It holds the formats of the files and the read-only view ``Session``. The view
reads the directory alone and never the index, so a session copied out of its project reads
the same.

1. The search writes ``session.json``, the descriptor of the session (``descriptor.py``).
2. Each trial is appended to ``trials.jsonl`` as events (``journal.py``). ``proposed`` is
   written when the optimizer asks, ``finished`` carries the cost and its components, and
   ``linked`` is written when the trial is promoted. The trial number is unique in the session.
   A reader keeps one line per trial, the event of the highest rank (``linked``, ``finished``,
   ``proposed``), and the last line at equal rank. A trial with a ``proposed`` line only, from a
   killed session, reads as ``running`` with no cost. The reader takes
   ``hydromodpy.trial.v2`` lines, as ``finished``, and ``hydromodpy.trial.v3`` lines, one by
   one, so a journal that mixes both reads.
3. A staged search writes one descriptor per phase in ``phases/<phase>/session.json``
   (``phase.py``). A phase has no journal of its own, and its trials are the lines of the
   session journal that carry its name.
4. The scored series of a trial go to ``trial_series/trial-NNNNNN.parquet``, one file per trial
   (``trial_series.py``). The file carries ``hmp.schema_version = hydromodpy.trial_series.v1``.
   A file without the key reads as ``v1``, and an unknown version is refused by name.
5. ``Session`` (``view.py``) reads all of it. It gives the trials, the best trial, the phases,
   the frozen configuration and the run that the best trial was promoted to.
   ``Session.of_run(run)`` returns the ``Session`` a run was promoted from, or ``None``, reading
   the lineage through ``session_dir_of``.
6. The indexer reads the same files to fill the session tables of the index.
7. ``summary.py`` holds ``SessionSummary``, ``session_summary(session)`` and
   ``summary_rows(summary)``, the one writer of the rows that the session page and ``hmp show``
   print. ``journal.py`` holds ``BOUND_TOLERANCE`` and ``on_bound``, which say that a value
   ended on a bound of its range.

A session of one case has one best run. On a session of several cases, ``best`` refuses and
``best_by_case`` holds them all. A field of the session descriptor goes in ``descriptor.py``,
with a version change if the format changes. A field of a trial line goes in ``TrialLine`` of
``journal.py``, something a phase records in ``PhaseDescriptor`` of ``phase.py``, a new read of
a session in a property of ``Session`` in ``view.py``, and a column of the trial frame in
``TRIAL_COLUMNS`` of ``view.py``.

The Zarr store
~~~~~~~~~~~~~~

``zarr_store/`` answers how the arrays of one run are stored. The store is Zarr 3, one per
run, in ``fields.zarr/``, and its metadata follows CF-1.11, ACDD-1.3 and UGRID-1.0. The class
``SimulationZarr`` is the door. It holds the store, its root group and its write lock.

1. ``zarr_schema.py`` opens the root group and writes the layout and the schema version
   (``initialise_root``).
2. A writer takes the store first and writes one thing. The writes of the mesh, the descent,
   the topography, the time, the CRS and the geographic raster are functions of
   ``geometry_writer.py`` (``write_mesh``, ``write_time``, ``write_crs`` and so on). The writes
   of fields and forcing are functions of ``zarr_writer.py`` (``write_field``,
   ``write_forcing_timeseries`` and ``write_array``, which both read).
3. ``SimulationZarr`` binds each function of the two writers and each function of
   ``zarr_reader.py`` as its methods. A signature is written once, in the module, and the
   method is the same function.
4. ``chunks.py`` picks balanced chunk sizes and, for large arrays, shard sizes. The constants
   are in ``constants.py``.
5. ``acdd.py`` composes the root attributes, and ``cf_validation.py`` checks a standard name
   against the bundled CF list in ``data/``.
6. ``zarr_finalizer.py`` gives the lock address and consolidates the metadata when the writes
   are done.
7. A reader calls ``read_field``, ``read_time`` and the other functions of ``zarr_reader.py``.
   Nothing here opens the index.

``mesh_layout.py`` says what the store keeps of the cell mesh and its line families. The table
that maps a field name to its place in the store and to its CF metadata is
``results/field_registry.py``. To add a stored field, add an entry in ``field_registry.py``,
then its write in ``zarr_writer.py``. A read of a stored field is a function in
``zarr_reader.py`` bound in ``simulation_zarr.py``. A new write is a function in
``zarr_writer.py``, or in ``geometry_writer.py`` for the geometry, bound in
``simulation_zarr.py``. A change of chunk or shard size goes in ``chunks.py`` and the targets of
``constants.py``, a root attribute in ``acdd.py``, and something the mesh must keep in
``mesh_layout.py``.

What is derived at read time
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``derive/`` answers what can be computed from a stored run at read time, so that it needs no
storage. A derived field is rebuilt from the stored ones each time it is asked for, and nothing
here writes to the index or to the run directory.

1. A caller asks for a variable through ``Run.read`` or ``Catalog.read``. ``reading.py`` is the
   one dispatch behind both. A field gives an ``xarray.DataArray``, a series a
   ``pandas.Series`` and a geographic feature a ``GeoDataFrame``.
2. If the name is a virtual field, ``virtual_fields.py`` computes it from the stored fields.
   Water table elevation and depth, seepage and release flux are of that kind.
3. ``accumulation.py`` routes drain and release fluxes down the descent of the run, range by
   range.
4. ``views.py`` reduces a field over the catchment or the active domain to a series
   (``saturated_fraction``, ``drainage_density``, ``persistence``, ``catchment_mean``), and
   ``budget_over`` totals a per-cell budget term over the catchment or a polygon.
5. ``time_alignment.py`` puts observed and simulated series on the same time axis, and
   ``run_period_edges`` gives the edges of the periods of a run. A timestamp in UTC without a
   time zone is ``naive_timestamp`` of ``core/time/period_aggregation.py``.
6. ``config_flags.py`` tells a reader which option to switch on when a field is missing, and
   says what a run kept of the budget.
7. ``catchment_aggregation.py`` writes the discharge and well_pumping series of one run, each
   term from the catchment row, its per-cell field or the domain row. The ``derive`` step of the
   workflow calls it. It reads the stored basin through ``basin_of_group`` of
   ``results/run/descent.py``, the one reader that the run views use too.
8. ``stream_network/`` reads the stream criterion on a finished run, as the next section says.

The other modules are ``derived.py`` (pure formulas for water table and flux per area),
``downsample.py`` (LTTB downsampling of dense series), ``recession.py`` (the recession cloud on
the Brutsaert-Nieber plane), ``mesh_quality.py`` (the quality of the stored mesh, one value per
cell) and ``run_memo.py`` (a per-run memo for heavy rebuilds shared by figures).

To add a computed field, write a function in ``virtual_fields.py``. A reduction over the
catchment goes in ``views.py``, or in ``catchment_aggregation.py`` for a series of the derive
step. A formula on stored arrays goes in ``derived.py``, a rule to align two series in time in
``time_alignment.py``, and a message about a missing option in ``config_flags.py``.

The stream criterion on a run
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``derive/stream_network/`` answers what a figure needs from a finished run to draw the stream
criterion, and which inputs the criterion reads. Calibration scores the criterion per trial
with the kernels of ``catchment/stream_network``. The modules here read the same inputs from a
stored run, so a figure draws the partition behind the number it illustrates. The figures in
``display/`` only draw what these modules return.

The kernels live in ``catchment/stream_network``. They are the simulated network
(``network.py``), the flowing cells and the extent masks (``extent.py``), the heads rule
(``heads.py``), the geometry and its partition (``geometry.py``) and the signed cost
(``cost.py``). The free ends are found in ``catchment/algorithms/network_heads.py``, the
visible-flow words and the numeric defaults are in ``core/scoring/stream_defaults.py``, and the
graph, the flood and the routing are in ``catchment/drainage/``.

1. ``criterion_inputs.py`` takes arrays, geometries and CRS. It holds the one function for each
   input that the trial and the figure both read: the cells a mapped line draws
   (``mapped_cells``), the free ends (``map_heads``), the outline cells (``catchment_cells``),
   the basin reference (``basin_reference``), the snapped outlet and the mean recharge
   (``criterion_recharge_of_run``). The trial calls it, and so does
   ``workflow/steps/run_outputs.py``, which keeps the outline cells, the open water and the mean
   recharge beside the run.
2. ``criterion_settings.py`` reads the settings that a run sealed for a network output, and
   falls back to the defaults where a key is absent (``network_criterion_settings``).
3. ``comparison.py`` rebuilds the comparison of a run with its mapped network
   (``network_comparison_from_run``, ``NetworkComparison``). It reads the solver centers, the
   open water, the outline cells and the mean recharge that the run kept, and decides none of
   them. A run that kept no mean recharge is refused when the seepage threshold is above zero.
4. ``run_extent.py`` counts the flow extents of a transient run, chunk by chunk, with the rules
   of ``catchment/stream_network/extent.py`` (``network_extents_from_run``,
   ``flow_geometry_from_run``). ``NetworkExtents.scored`` holds the cells the criterion scores.
5. ``heads_view.py`` gives the heads of the mapped network for the map that shows them
   (``network_heads_view_from_run``).
6. ``routing_surface.py`` builds the model top that the routing figures explain, once per run
   (``routing_surface_from_run``, ``RoutingSurface``).
7. ``depressions.py`` floods that surface twice, from every escape and from the outlet alone
   (``depression_fill``, ``DepressionFill``, ``Flood``).

``display`` (all the figures of the stream criterion and of the routing surface),
``calibration``, ``workflow`` and ``results`` itself import this folder. ``catchment``,
``solver`` and ``model`` do not. What they share with the criterion lives in
``catchment/stream_network/``, ``catchment/drainage/``, ``model/forcing/`` and
``core/scoring/``.

A change to what counts as a stream goes in ``catchment/stream_network/network.py`` or
``extent.py``, and then both calibration and the redraw follow. A new input of the criterion
goes in ``criterion_inputs.py``, on arrays, called by the trial and by ``run_outputs``. A new
default goes in ``core/scoring/stream_defaults.py`` and never as a literal in a caller. A new
computation that a stream figure needs is a module here that takes a ``Run``, and never a figure
that calls ``catchment``. The tests are in ``tests/unit/results/stream/``,
``tests/unit/catchment/stream_network/`` and ``tests/unit/results/``, and
``tests/unit/architecture/test_the_stream_criterion_reads_once.py`` holds that each input has
one writer.

Leaving the project
~~~~~~~~~~~~~~~~~~~

``export/`` answers how a sealed run, or a summary of many runs, leaves the project in a form
that others can find and reuse. It builds the RO-Crate FAIR view of a sealed directory, copies a
run or a summary out of the tree, and packs a whole project with its data. Everything is read
from the directory and the index is never opened.

STAC and the standalone PROV view moved to ``hydromodpy_annex/export/``. They are export
formats of the port (``results/exporters/``), registered by the ``hydromodpy.export.format``
entry points, so ``format = "stac"`` and ``format = "prov"`` are refused unless the annex can be
imported. What stays here is what RO-Crate reads, which is the document built by
``build_prov_document`` with its activities and identifiers. A run directory may still carry
``stac-item.json`` or ``prov.jsonld`` written by an annex. The seal keeps not inventorying them,
because they belong to the view and the stored layout names them.

1. ``directory.py`` reads the seal of a run or a job and builds one ``FairExportContext``
   (``context.py``).
2. A FAIR view is one format of the export port, ``rocrate`` here, and ``stac`` and ``prov`` in
   the annex. The view writer receives the context in its ``ExportJob``, so every view describes
   the same seal.
3. ``context.to_json`` writes every FAIR view atomically and whole, through a temporary file and
   one rename.
4. ``publish.py`` copies a run or a summary out of the tree, as a directory or a tar. A run copy
   holds the results, the final state, the inputs, ``mesh/`` and ``products.json`` by default,
   and ``--without`` removes a part. It refuses a replay not classed ``bit``, writes
   ``PUBLICATION.json`` and redacts the host, the user and the absolute paths. A copy also drops
   the ``deliver_to`` key of every ``[[export]]`` block, so a copy names no destination.
   ``verify`` checks a copy. The source records the copy with ``kind = "copy"`` in
   ``published.jsonl``, and a line with ``kind = "delivery"`` is written by
   ``project/deliver.py`` for each file sent to a ``deliver_to`` destination.
5. ``project_package.py`` writes a whole project with its data for ``hmp publish --package``.
6. ``summary_tables.py`` and ``campaign_summary.py`` write the table, the page, the README and
   the crate of a summary.
7. ``zenodo.py`` renders the Zenodo deposit metadata of one sealed run, with title, creators,
   licence, keywords, version and related identifiers. It writes nothing. The publication writes
   ``.zenodo.json`` at the root of each copy, from the seal or from ``[publication]``.

``rocrate.py`` holds the RO-Crate 1.1 metadata, declared in ``results/exporters``, and
``summary_tables.py`` writes a table of runs as Parquet, CSV and GeoPackage. To add a view
outside the wheel, write a writer on the export port, as the annex does, and publish it on the
``hydromodpy.export.format`` entry-point group. A field the views share goes in
``FairExportContext`` of ``context.py``, filled in ``directory.py``. A file that a view writes
goes through ``to_json`` so the write stays atomic. Something removed from a published copy is
set in the redaction of ``publish.py``, and a column of a summary table in ``summary_tables.py``.

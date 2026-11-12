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

The package answers how a run is stored, sealed, found and read back. The stored arrays are at :doc:`/reference/outputs` and the contract is :doc:`../storage-layout`.

Storage and the seal
~~~~~~~~~~~~~~~~~~~~

``storage/contract.py`` is the place to look for a name. ``CERTIFIED_RUN_ENTRIES`` lists what
the seal inventories and ``UNSEALED_RUN_ENTRIES`` what it never does. A new file enters
``contract.py`` first, then ``tests/unit/results/test_run_layout_contract.py``.

The seal is written in one order. First come the CRS in WKT2, the attributes of ``fields.zarr``,
the value digests, the copy of the sealed mesh, the class of a replay and the record of the run.
Then ``README.md`` follows, and its section "What this run does not give" is read from the keys
of the digests. ``profile.json`` sits outside the seal, because it describes one machine, and
``figures/``, ``exports/`` and ``report/`` are written after it and never inventoried.

``record/`` writes ``manifest.json`` on the model of ``hydromodpy/schema/seal.py``, with one
digest per array. A field rounded for storage is hashed in double precision before the rounding, so ``bit`` covers the values as computed. A replay
compares its digests with the seal of its source and writes ``bit`` or ``deviation``.

The catalog
~~~~~~~~~~~

The index ``.hmp/index.duckdb`` is derived from the run and session directories. ``Catalog`` (``facade.py``) reads it and the indexer is the only writer.
The indexer takes the lock ``.hmp/index.duckdb.lock``, reads every run, session and kept trial
into a staging file, checks that it still holds the lock, and publishes the file in one rename.
``rebuild_index`` does the whole tree and ``index_new_runs`` does a diff. A change of
``index_schema.py`` is a full rebuild. ``discovery.py`` turns a reference (a name, an id,
``@last``, ``@best:METRIC``) into a run.  ``liveness.py`` and ``privacy.py`` never open the index, so ``hmp doctor`` answers while it is rebuilt. ``SIMULATIONS_FROM`` in ``constants.py`` is the one join of a run row to the codes of
its solver, status, flow regime and mesh topology.

To add an index column, change ``index_schema.py``, its read-back in ``indexer.py`` and the schema version.

The run view
~~~~~~~~~~~~

``Run`` is one run directory and ``RunSet`` a view over several. The rows of a run come from
its own Parquet files and its arrays from its own Zarr store, so the index only finds the run.
``Run`` (``view.py``) loads its row on first use. Tabular reads go to ``tables.py``, and the
mixins ``geographic.py``, ``timeseries.py`` and ``hydrographic.py`` add the rest. Providers hang
on the run (``run.array``, ``run.probe``, ``run.periods``, ``run.descent``), and ``sealed.py``
reads what the seal says. To add an accessor, write a provider in this folder and bind it in
``view.py``. ``test_run_surface.py`` caps ``Run`` at 50 public attributes.

The session
~~~~~~~~~~~

A calibration session leaves files in ``sessions/<case>/``, and ``Session`` reads that directory
alone and never the index, so a session copied out of its project reads the same. The search
writes ``session.json`` (``descriptor.py``) and appends each trial to ``trials.jsonl``
(``journal.py``) as the events ``proposed``, ``finished`` and ``linked``. A reader keeps one
line per trial, the event of the highest rank, so a trial with a ``proposed`` line only, from a
killed session, reads as ``running`` with no cost.  A field of a trial line goes in ``TrialLine`` of ``journal.py``, and a format change needs a version change.

The Zarr store
~~~~~~~~~~~~~~

``SimulationZarr`` is the door to ``fields.zarr/``. A writer takes the store first and writes
one thing, with geometry in ``geometry_writer.py`` and fields and forcing in ``zarr_writer.py``.
``SimulationZarr`` binds each function of the writers and of ``zarr_reader.py`` as its methods,
so a signature is written once, in the module. To add a stored
field, add an entry in ``results/field_registry.py``, then its write in ``zarr_writer.py``,
bound in ``simulation_zarr.py``.

What is derived at read time
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``derive/`` computes from a stored run what needs no storage, and nothing here writes to the
index or to the run directory. ``Run.read`` and ``Catalog.read`` go through one dispatch,
``reading.py``. A virtual field is computed from the stored ones by ``virtual_fields.py``,
``views.py`` reduces a field over the catchment to a series, and ``time_alignment.py`` puts
observed and simulated series on one axis. To add a computed
field, write a function in ``virtual_fields.py``.

The stream criterion on a run
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Calibration scores the stream criterion per trial with the kernels of
``catchment/stream_network``. ``derive/stream_network/`` reads the same inputs from a stored
run, so a figure draws the partition behind the number it illustrates. ``criterion_inputs.py``
holds the one function for each input that the trial and the figure both read, and
``workflow/steps/run_outputs.py`` calls it to keep the outline cells, the open water and the
mean recharge beside the run. A change to what counts as a stream goes in
``catchment/stream_network/``. A new input goes in ``criterion_inputs.py``, and a new default in
``core/scoring/stream_defaults.py``, never as a literal in a caller.
``tests/unit/architecture/test_the_stream_criterion_reads_once.py`` holds that each input has one
writer.

Leaving the project
~~~~~~~~~~~~~~~~~~~

``export/`` builds the RO-Crate view of a sealed directory, copies a run or a summary out of
the tree, and packs a whole project. ``directory.py`` reads the seal and builds one
``FairExportContext``, so every view describes the same seal. A view is one format of the export
port (``results/exporters/``), and the STAC and standalone PROV views live in ``hydromodpy_annex/export/``.
``publish.py`` refuses a replay not classed ``bit``, redacts the host, the user and the absolute paths, and drops the ``deliver_to`` key of
every ``[[export]]`` block.

Logs
~~~~

``core/logging.py`` keeps one router on the package logger, and the router sends each record to
the files in the context variable ``RUN_SINKS``. So two runs in two threads fill two
``run.log`` files and no line crosses. 

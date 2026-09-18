hmp process
===========

Drive a capability as an external process. A capability is a function from a
validated input document to a directory of sealed artefacts: it opens no
workspace, no catalog and no database, and it registers nothing in the user's
state directory.

Whether it reaches the network is declared, not assumed. Each description lists
under ``hmp:invocation.network`` every host the capability contacts, and an empty
list means it runs on a node with no route out at all -- which is what
``terrain-delineate`` declares. ``data-fetch`` declares the four providers it may
reach, one per source it serves, because that is the set an orchestrator has to
allow before it has read the request; which of them a given run reached is named
host by host under ``hosts`` in ``outputs/fetch.json``. A gate records every name the process resolves and every
address it connects to and refuses one the declaration does not carry, so the
list is checked rather than promised.

It is not, however, free of the filesystem outside the job. Each description
lists under ``hmp:invocation.writes_outside_jobdir`` every location the
capability needs writable; both capabilities name ``$TMPDIR``, where
``terrain-delineate`` assembles one catchment per outlet and where ``data-fetch``
gives each fetch a scratch directory it owns. An empty list means the job
directory is the only thing that has to be writable.

The invocation contract
-----------------------

Before invoking, the caller creates the job directory and writes **exactly
one file** into it::

    $JOBDIR/
    `-- request.json

That is the whole precondition. A directory that does not exist, or that
carries no ``request.json``, is a usage error and exits **2** without
writing anything.

``request.json`` uses the OGC API Processes execute-request shape::

    {
      "process": {"id": "terrain-delineate", "version": "1.0.0"},
      "inputs": {
        "dem": {"href": "/data/dem_valley.tif",
                "type": "image/tiff; application=geotiff"},
        "outlets": [{"site_id": "valley", "x": 300112.5, "y": 6701262.5}],
        "crs_project": "EPSG:2154",
        "dem_correction_type": "breach",
        "snap_distance_m": 100
      }
    }

``process.version`` is advisory: a different patch or minor is a warning
carried in the outcome, a different **major** exits 11. Unknown members of
the envelope are warnings; unknown members of ``inputs`` exit 14, pointed at
the key the document wrote.

Sub-actions
-----------

``hmp process list [--format {table,json,csv}]``
    The capabilities this build serves, with their version, their major and
    the artefacts each declares.

``hmp process describe <id> [--major N] [--format {table,json,csv}]``
    The machine-readable description of one capability: its inputs with their
    JSON Schema, its declared artefacts with the path each takes under the job
    directory, and the typed failures it can return with the exit code of
    each. ``--format json``, the default, writes the document **byte for
    byte** as it ships in the wheel; the other two flatten it for a human.

``hmp process run <id> --job DIR``
    Run one. **stdout carries exactly one JSON document and nothing else**,
    byte for byte the content of ``DIR/outcome.json``; every human line goes
    to stderr. The exit code is the typed one of the outcome, so a caller
    that tests ``$?`` and a caller that reads the document agree. SIGTERM
    unwinds: the outcome says ``dismissed``, nothing is sealed, exit 130.
    Re-running the same request into a directory that already holds it is a
    reuse, below.

``hmp process verify --job DIR [--format {table,json,csv}]``
    Re-check a finished directory against its own seal, reading only the
    disk: every artefact still hashes to what the seal recorded, the input
    set still digests to the id it carries, and the outcome names the same
    job. Nothing is repaired and nothing is rewritten. Exits **16** when the
    directory does not verify. It is pointed at directories it did not
    write, including ones a transfer truncated: it reports, it never crashes
    on them.

The process description
-----------------------

One JSON document per capability, shipped inside the wheel under
``hydromodpy/schema/processes/``. The file name carries the **major**
version, ``terrain-delineate@1.json``: a breaking change to inputs or outputs
mints ``@2`` and both ship side by side, while a compatible change bumps
``version`` inside the existing file. A caller pins the major and survives a
minor bump. ``index.json`` maps each id to its file.

Nothing in it is written by hand. It is generated from the capability
declaration, the Pydantic request model and the exit-code mapper by
``python -m tools.processes``, and ``tests/unit/schema/test_process_descriptions.py``
refuses a committed document the generator no longer reproduces. That gate is
why the description cannot claim an exit code the process does not produce,
nor an artefact path a real run does not write.

A third party writes their own shim against this document -- an OGC API
Processes façade, a Galaxy tool, a workflow node -- without patching
HydroModPy and without importing it. HydroModPy serves nothing over HTTP and
never will.

The capabilities this build serves
----------------------------------

``terrain-delineate``
    Corrects a DEM, routes flow and delineates the upstream area of each
    declared outlet. Reaches no network.

``data-fetch``
    Asks one declared data source for one variable over a bounding box, a
    vector mask or a list of station codes, and seals what came back.

    The extent is an **input**, never an object the process went looking for:
    either ``extent``, a bounding box that carries the CRS it is expressed in,
    or ``mask``, a vector file whose bounds are the extent. The second is what
    chains the two capabilities -- the GeoPackage ``terrain-delineate`` seals is
    a mask ``data-fetch`` reads -- through a directory rather than through an
    object graph.

    A source is asked for through a tagged document: ``source.id`` selects it and
    the rest of the object configures it, so the description carries the exact
    shape each source accepts instead of an option bag validated by nothing::

        {"process": {"id": "data-fetch", "version": "1.0.0"},
         "inputs": {
           "source": {"id": "hubeau-piezometry", "product": "level"},
           "mask": {"href": "../4711/outputs/watershed.gpkg"},
           "period": {"start": "2020-01-01", "end": "2020-12-31"}}}

    Which artefact it writes depends on the source's payload kind, and the run
    writes exactly one of them: ``outputs/points.parquet``,
    ``outputs/fields.nc``, ``outputs/features.gpkg`` or ``outputs/raster.tif``.
    ``outputs/fetch.json`` is always there, and it names the one that was
    written, the hosts this run contacted, the extent that was **really
    queried** and the CRS it was really queried in -- a WGS84 box asked for a
    DEM reaches the Geoplateforme in Lambert-93 metres, and nothing else on disk
    says so.

    A provider that holds nothing inside the extent is an answer, not a failure:
    the run succeeds, ``fetch.json`` says ``"empty": true``, and no data artefact
    is sealed.

What the directory holds afterwards
-----------------------------------

::

    $JOBDIR/
    |-- request.json      written by the CALLER, the only file it writes
    |-- inputset.json     what was consumed: resolved, hashed, licence-annotated
    |-- provenance.json   how it ran: tool, commit, interpreter, backend, packages
    |-- outcome.json      typed status, exit code, timing, errors
    |-- manifest.json     the seal, written LAST and atomically
    |-- outputs/          the declared artefacts
    `-- logs/             diagnostics, not an artefact, not in the seal

The order above is the write order, and the invariant it buys is the one a
caller outside the process relies on:

  ``manifest.json`` exists **if and only if** the job succeeded and every
  declared output is present and hashed. Its absence is never ambiguous.

Running the same job twice
--------------------------

``job_id`` is a **content address**: the sha256 of the process identity and of
the resolved inputs, every file link replaced by the digest of its bytes. Two
byte-identical submissions therefore carry one id, whatever the directory is
called and wherever it was copied to, and the description states the rule under
``hmp:invocation.idempotency``.

Pointing ``run`` at a directory that is already sealed is answered from that id
and never by re-running:

* **the same id** -- nothing is written, stdout carries the stored
  ``outcome.json`` with ``"reused": true``, and the process exits **0**. That
  gives a shim deduplication and safe retry with no job store and no database.
* **a different id** -- refused as a usage error, exit **2**, nothing written.
  A job directory holds one job, and running would overwrite a seal, a job id
  and a set of artefacts somebody else may already have read.

``"reused"`` states what **this invocation** did, not what the job did, and it
is the one member where stdout and ``outcome.json`` differ: the document on
disk was written by the run that did the work and keeps ``false``. Rewriting it
would break the seal that hashes it.

A reuse does not re-hash the artefacts; it trusts the seal. ``hmp process
verify`` is the verb that does not.

A worked example
----------------

.. code-block:: console

   $ mkdir -p /scratch/jobs/4711
   $ cat > /scratch/jobs/4711/request.json <<'JSON'
   {"process": {"id": "terrain-delineate", "version": "1.0.0"},
    "inputs": {"dem": {"href": "/data/dem_valley.tif"},
               "outlets": [{"site_id": "valley", "x": 300112.5, "y": 6701262.5}],
               "crs_project": "EPSG:2154", "snap_distance_m": 100}}
   JSON
   $ hmp process run terrain-delineate --job /scratch/jobs/4711 \
       > /scratch/jobs/4711.stdout.json 2> /scratch/jobs/4711.stderr.log
   $ echo $?
   0
   $ hmp process verify --job /scratch/jobs/4711
   /scratch/jobs/4711: sealed, and every artefact still hashes to what the seal recorded

The produced directory opens with plain readers -- ``geopandas``,
``rasterio``, ``json`` -- with nothing of HydroModPy imported. That is
asserted by ``tests/e2e/process/test_stdout_is_one_json_document.py``.

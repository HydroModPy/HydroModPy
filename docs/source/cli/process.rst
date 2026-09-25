hmp process
===========

Drive a capability as an external process. A capability is a function from a
validated input document to a directory of sealed artefacts: it opens no
workspace, no catalog and no database, and it registers nothing in the user's
state directory.

Whether it reaches the network is declared, not assumed. Each description lists
under ``hmp:invocation.network`` every host the capability contacts, and an empty
list means it runs on a node with no route out at all -- which is what
``terrain-delineate`` and ``domain-build`` declare. ``data-request`` declares
every provider a source it serves may reach, because that is the set an
orchestrator has to allow before it has read the request; which sources a given
run asked is listed file by file in ``outputs/request.json``. A gate records
every name the process resolves and every address it connects to and refuses one
the declaration does not carry, so the list is checked rather than promised.

It is not always free of the filesystem outside the job either. Each description
lists under ``hmp:invocation.writes_outside_jobdir`` every location the
capability needs writable. ``terrain-delineate`` and ``data-request`` name
``$TMPDIR``, where the first assembles one catchment per outlet and the second
keeps the download cache of the managers, indexed in memory and removed with
the job; ``domain-build`` names nothing,
because the job directory is the only thing it writes into. An empty list means
exactly that, and a gate runs the capability under a controlled ``TMPDIR`` and a
controlled ``HOME`` to hold it to it.

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

``hmp process chain --root DIR``
    Run several capabilities in a row, in one command. ``DIR`` carries
    ``chain.json`` and nothing else; the verb creates one job directory per
    step, **writes each** ``request.json`` **itself**, and fills the file
    inputs of a step from the artefacts an earlier one sealed. stdout carries
    exactly one JSON document, byte for byte the content of
    ``DIR/chain-outcome.json``, and the exit code is the typed one of the step
    that stopped the chain. A document that does not resolve leaves ``DIR``
    exactly as it was staged: no step directory, no report. Detailed below.

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

``domain-build``
    Places the bottom of the aquifer below a topographic surface and seals the
    vertical extent that comes out: ``outputs/bottom.tif``,
    ``outputs/thickness.tif``, ``outputs/active_cells.tif`` and
    ``outputs/domain.json``, which carries the grid, the depth model and the
    extent over the active cells. Reaches no network, and writes nowhere but
    its job directory.

    The two elevation rasters are float64 and carry **NaN** outside the domain,
    declared as their nodata. Not the terrain's own sentinel: a flat substratum
    clamps a nodata cell instead of preserving it, and neither depth model marks
    a cell the mask excluded, so a consumer masking on a finite tag would read a
    fabricated elevation. ``outputs/active_cells.tif`` says the same thing in
    integers, 1 for active and 0 for not.

    The terrain must carry a CRS and an axis-aligned grid, and the mask must be
    made of polygons. Each of the three is refused rather than worked around: a
    rotated grid has no cell size for the document to publish, and a layer of
    lines burns a one-cell-wide diagonal that would come back as a successful
    job with a sliver for a domain.

    It takes the ``[domain.depth_model]`` section of a project verbatim, and
    only that section: ``domain.supports`` is built by providers that read
    loaded forcings and a workspace, which a capability has neither of. The
    working CRS is the terrain's own, so a DEM carrying none is refused rather
    than stamped with one the caller asserted.

    The top surface is **not** re-emitted. ``domain.json`` carries the digest of
    the raster the bottom was derived from, so a reader holding a DEM can prove
    it is that one, and the largest write of the job is not doubled to produce a
    copy of its own input. The two artefacts a chain feeds it are the corrected
    DEM and the catchment ``terrain-delineate`` seals.

    A depth model of kind ``raster_substratum`` or ``raster_thickness`` also
    takes ``substratum``, the raster the bottom is read from. It carries its own CRS, is reprojected onto the grid of
    the DEM, and must cover every active cell: the mask is the extent. Its digest
    is recorded like the DEM's. Any other kind refuses a ``substratum``::

        {"process": {"id": "domain-build", "version": "1.0.0"},
         "inputs": {
           "dem": {"href": "/scratch/jobs/4711/outputs/dem_corrected.tif"},
           "depth_model": {"kind": "constant_thickness", "thickness": 30.0},
           "mask": {"href": "/scratch/jobs/4711/outputs/watershed.gpkg"},
           "mask_layer": "watershed"}}

``data-request``
    Loads ``[data]`` sections over a bounding box, a vector mask or a list of
    station codes, and seals one file per variable and source, cut to the
    extent and the period asked for. The sections are the models of the project
    TOML, so what a project asks for, a job asks for the same way; this is the
    document ``hmp data get`` reads, under ``inputs``.

    The extent is an **input**, never an object the process went looking for:
    ``extent.bbox`` with ``extent.crs``, ``extent.mask``, a vector file whose
    shape bounds the request, or ``extent.station_ids``. The mask is what chains
    the two capabilities -- the GeoPackage ``terrain-delineate`` seals is a mask
    ``data-request`` reads -- through a directory rather than through an object
    graph::

        {"process": {"id": "data-request", "version": "1.0.0"},
         "inputs": {
           "data": {"piezometry": {"sources": [{"source": "hubeau", "product": "level"}]},
                    "dem": {"sources": [{"source": "ign_geoplateforme_dem"}]}},
           "extent": {"mask": {"href": "/scratch/jobs/4711/outputs/watershed.gpkg"}},
           "period": {"start": "2020-01-01", "end": "2020-12-31"}}}

    The mask is named in full, and it has to be: a **relative** input path is
    resolved against the job directory and refused if it walks out of it, which
    is what the directory of another job is. ``hmp process chain`` writes that
    path for the caller. A ``sha256`` beside ``href`` pins its bytes.

    Each variable lands under ``outputs/`` as ``<variable>_<source>`` with the
    suffix of its kind: ``.parquet`` for chronicles, ``.nc`` for grids,
    ``.tif`` for rasters, ``.gpkg`` for vectors. ``outputs/request.json`` is
    always there: it lists each file with its sha256, CRS, box, period and
    unit, and every variable that answered nothing.

    A provider that holds nothing inside the extent is an answer, not a failure:
    the run succeeds, the report says ``"empty": true`` for that variable, and
    no data file is sealed for it. A variable that **fails** fails the job, with
    the typed exit code of its error, and nothing is sealed. A ``custom``
    source is refused before anything is written: a job has no user files to
    read. Plugin sources are asked under ``installed``, by name, with the
    options their constructor takes.

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

Chaining capabilities
---------------------

Capabilities compose through the disk: the GeoPackage ``terrain-delineate``
seals is a mask ``data-request`` reads, and the corrected DEM it seals beside
it is the top surface ``domain-build`` places a bottom under. Asking for a variable
over a watershed, or for the geometry of an aquifer under one, is therefore two
jobs, and ``chain`` is the verb that runs them as one command.

The caller writes **one** document at the chain root::

    $CHAINDIR/
    `-- chain.json

::

    {"steps": [
      {"id": "delineate",
       "process": {"id": "terrain-delineate", "version": "1.0.0"},
       "inputs": {"dem": {"href": "/data/dem_valley.tif"},
                  "outlets": [{"site_id": "valley", "x": 300112.5, "y": 6701262.5}],
                  "crs_project": "EPSG:2154"}},
      {"id": "fetch",
       "process": {"id": "data-request"},
       "inputs": {"data": {"piezometry": {"sources": [{"source": "hubeau", "product": "level"}]}},
                  "period": {"start": "2020-01-01", "end": "2020-12-31"}},
       "links": [{"member": "extent.mask", "step": "delineate",
                  "output": "watershed_vector"}]}
    ]}

A **link** is the whole point: ``member`` is the input of this step to fill
(a dotted path such as ``extent.mask`` names a member nested in another),
``step`` is an earlier step of the chain, and ``output`` is an artefact of that
step **as its capability declares it** -- ``hmp process describe`` lists the
names. The chain turns it into the absolute path that artefact takes, which is
the only spelling a job directory accepts for a file in another one.

Steps run in the order they are written, each in its own job directory named
after its rank and its id::

    $CHAINDIR/
    |-- chain.json          written by the CALLER, the only file it writes
    |-- chain-outcome.json  one record per declared step, in order
    |-- 01-delineate/       an ordinary job directory, sealed
    `-- 02-fetch/           its request.json names 01-delineate/outputs/watershed.gpkg

Four rules, each of them checkable from the outside:

* **a chain is refused before it runs.** A step naming a capability this build
  does not serve, a link pointing forward, at itself or at an artefact the
  producing capability does not declare: each is refused with the pointer of
  the member that carries it, while the root is still empty. Nothing is run and
  nothing is written.
* **a failing step stops the chain**, and the steps after it are recorded as
  ``skipped`` -- a statement that they did not run, never a failure attributed
  to them. The exit code of the chain is the typed exit code of the step that
  stopped it. The status of a step is read off **its exit code** and never off
  the document it printed; a step whose document says otherwise has its
  disagreement published as a fault of that step.
* **a linked artefact that the run did not produce refuses its reader.** An
  artefact declared optional is one a run may not write, so the chain checks
  the file is there before starting the step that reads it.
* **idempotency composes.** Running the same chain into the same root again
  re-submits each step with a byte-identical request, so each one is a reuse:
  nothing is re-run, and ``chain-outcome.json`` says ``"reused": true`` for
  each.

A root already carrying a ``chain-outcome.json`` that is not a file is a usage
error, refused before the first step: a chain that ran two capabilities and
then had nowhere to write its report would have done the work and said so
nowhere.

A step directory carries exactly what any job directory carries, and the chain
writes nothing inside it beyond the ``request.json`` a caller would have
written by hand. ``hmp process verify --job $CHAINDIR/01-delineate`` is the
same verb, on the same seal.

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

The same two jobs, chained:

.. code-block:: console

   $ mkdir -p /scratch/chains/17
   $ cat > /scratch/chains/17/chain.json <<'JSON'
   {"steps": [
     {"id": "delineate", "process": {"id": "terrain-delineate", "version": "1.0.0"},
      "inputs": {"dem": {"href": "/data/dem_valley.tif"},
                 "outlets": [{"site_id": "valley", "x": 300112.5, "y": 6701262.5}],
                 "crs_project": "EPSG:2154"}},
     {"id": "fetch", "process": {"id": "data-request"},
      "inputs": {"data": {"dem": {"sources": [{"source": "ign_geoplateforme_dem"}]}}},
      "links": [{"member": "extent.mask", "step": "delineate",
                 "output": "watershed_vector"}]}]}
   JSON
   $ hmp process chain --root /scratch/chains/17 \
       > /scratch/chains/17.stdout.json 2> /scratch/chains/17.stderr.log
   $ echo $?
   0
   $ ls /scratch/chains/17
   01-delineate  02-fetch  chain.json  chain-outcome.json

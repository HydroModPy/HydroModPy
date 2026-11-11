Package: schema
===============

.. include:: ../../../../../hydromodpy/schema/README.md
   :parser: myst_parser.sphinx_
   :start-line: 1

Modules
-------

.. hmp-module-table:: schema

Inside the package
------------------

``results/record/manifest.py`` extends the seal of ``seal.py`` for a run, because the
blocks of a run are types of ``results`` and ``schema`` has no edge towards it. The same
rule shapes the two folders of published files. ``processes/`` and ``results/`` hold
package data, and their ``__init__.py`` reads and writes the files and imports no model.
The caller pairs a file with its model.

The job directory is the whole interface between a caller and a capability, and nothing
in ``job/`` opens a database, a socket or a workspace. ``manifest.json`` is the seal of a
finished job, at ``manifest_version`` 4 and ``profile = "job"``, the common model of
``seal.py``. It carries ``request_id``, the content address of the request, and
``outcome.json`` keeps that value under its field ``job_id``. ``read_job_seal`` also
reads the older ``hmp-manifest/v2`` family, in memory, without rewriting the file. The
caller creates the directory and writes ``request.json``. The process writes ``outputs/``,
``inputset.json``, ``provenance.json``, ``outcome.json`` and ``manifest.json``, in that
order, so the seal exists if and only if the job succeeded. A capability is added as a
``CapabilityDecl`` and a worker beside the code.

The files of ``processes/`` are generated. ``python -m tools.processes`` writes
``index.json`` and one ``<id>@<major>.json`` per capability from its ``CapabilityDecl``,
and a test refuses a committed file that the declaration no longer reproduces.

The files of ``results/`` are the JSON Schemas of the stored formats, one
``<name>.<version>.json`` per document that a run, a session, a plan or a publication
writes, and the one that ``hmp calibrate --format json`` prints. A reader outside Python
validates a document against them without importing anything. They are generated from the
Pydantic models with ``model_json_schema()``, and
``tests/unit/schema/test_results_schemas_match_models.py`` refuses a committed file that
its model no longer reproduces. Run as a script, it writes them again. The plan is
``plan.v2.json``, because a plan keeps its cases in ``cases.csv``.

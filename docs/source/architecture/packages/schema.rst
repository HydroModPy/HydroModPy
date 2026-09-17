schema
======

``hydromodpy.schema`` exposes the JSON Schema export and the
partial-field validator that any frontend (Angular, React,
Jupyter widget) consumes, and the job-directory contract a
capability is invoked through as an external process. It is the
only public, stable contract for non-Python integrations.

Sub-modules
-----------

- ``schema/export.py`` -- ``export_full_schema(output_dir)`` writes
  three JSON files under ``output_dir/``:

  - ``config.json`` -- full JSON Schema of ``HydroModPyConfig``;
  - ``config_meta.json`` -- ordered TOML sections, UI groups,
    titles;
  - ``field_validators.json`` -- flat
    ``field_path -> validator_type`` (enum, number, date, ...).

- ``schema/partial_validator.py`` -- ``validate_field(path,
  value)`` resolves the dotted path on ``HydroModPyConfig``, picks
  the matching ``pydantic.TypeAdapter``, and returns a lightweight
  ``ValidationResult``. Lookups are memoised, runs under 50 ms.

- ``schema/capability.py`` -- ``CapabilityDecl`` and ``OutputDecl``:
  what one externally invocable capability declares about itself,
  before any of it runs. Stdlib only, and the request model is
  carried as an opaque type, so the declaration stays readable by a
  layer that owns no engine.

- ``schema/job/`` -- the job-directory contract, below.

The job directory
-----------------

One directory is the whole interface of a capability invoked as an
external process. The caller creates it, writes ``request.json``
into it, and hands over the path::

    $JOBDIR/
    |-- request.json      written by the CALLER, the only file it writes
    |-- inputset.json     what was consumed: resolved, hashed, licence-annotated
    |-- provenance.json   how it ran
    |-- outcome.json      typed status, exit code, timing, errors
    |-- manifest.json     the seal, written LAST and atomically
    |-- outputs/          the declared artefacts
    |-- logs/             diagnostics, not an artefact, not in the seal
    `-- progress.ndjson   appended while it runs, not an artefact

The order above is the write order, and the invariant it buys is
the one a caller outside the process relies on:

  ``manifest.json`` exists **if and only if** the job succeeded and
  every declared output is present and hashed. Its absence is never
  ambiguous.

- ``job/layout.py`` -- the names, the write order, and
  ``ALLOWED_JOB_ENTRIES``, asserted as a subset so a directory
  already on disk never becomes illegal.
- ``job/directory.py`` -- ``JobDirectory``: resolves its root once,
  so containment is decidable. A relative input path is resolved
  against the job directory and must stay inside it, symlinks
  followed; an absolute path is read where the orchestrator staged
  it; any URI scheme other than ``file:`` is refused, because a
  capability never opens the network.
- ``job/request.py`` -- the OGC API Processes execute-request shape,
  read and refused in one typed shape, plus ``content_address()``
  for the ``job_id``.
- ``job/inputset.py`` -- the input set as a first-class object,
  whose id digests the **complete** resource array, with a licence
  per resource and a rollup that never refuses to seal.
- ``job/outcome.py`` -- the typed outcome, which refuses to carry a
  status that contradicts its own exit code.
- ``job/seal.py`` -- ``seal_job()`` and ``verify_job()``.
- ``job/documents.py``, ``job/digest.py``, ``job/refusal.py`` --
  atomic writes, the two digests, and the pointed refusal.

Annotations carried by the schema
---------------------------------

Each field of ``config.json`` keeps the ``json_schema_extra``
annotations declared by the Pydantic models:

- ``widget_type`` (``slider``, ``text``, ``select``, ``date``,
  ``file``, ``map``);
- ``unit`` (canonical SI: ``m``, ``m/s``, ``1/m``);
- ``display_name_fr`` and ``display_name_en``;
- ``help_text_fr`` and ``help_text_en``;
- ``display_min`` and ``display_max`` for sliders;
- ``profile`` (``user`` / ``dev`` / ``expert``).

These annotations are the contract between the Pydantic models and
any UI integration. Honour them and you avoid a custom mapping
layer.

Key public symbols
------------------

- ``hydromodpy.schema.export.export_full_schema``
- ``hydromodpy.schema.partial_validator.validate_field``
- ``hydromodpy.schema.partial_validator.ValidationResult``
- ``hydromodpy.schema.capability.CapabilityDecl``
- ``hydromodpy.schema.job.JobDirectory``
- ``hydromodpy.schema.job.read_request``
- ``hydromodpy.schema.job.seal_job`` and
  ``hydromodpy.schema.job.verify_job``

CLI bindings
------------

- ``hmp dev schema export --output ./schema/`` -> three JSON files.
- ``hmp dev schema validate-field <path> <value>`` -> JSON
  ``ValidationResult``.

Both subcommands live under ``hydromodpy/cli/commands/dev/schema.py``.

Recommended reading path
------------------------

1. ``hydromodpy/schema/export.py``
2. ``hydromodpy/schema/partial_validator.py``
3. The composition root ``hydromodpy/config/hydromodpy_config.py``
   to see what is exported.
4. One model that ships rich annotations (for example
   ``hydromodpy/physics/flow/flow_config.py``).
5. ``hydromodpy/schema/job/layout.py``, then ``job/directory.py``,
   for the external-process side.

Layer-matrix neighbours
-----------------------

- Allowed targets: ``core``, ``schema``, ``config``.
- Allowed sources: every other layer (the schema export is the
  most central public contract).
- The schema export must stay deterministic. Do not introduce
  side-effects or environment-dependent fields.

See also
--------

- :doc:`/architecture/overview/frontend-hooks` -- design rationale
  for the integration surface.
- :doc:`/architecture/how-to/build-a-frontend` -- step-by-step
  recipe (Angular, React).
- :doc:`/architecture/how-to/add-a-config-field` -- adding a field
  with the annotations the schema consumes.
- :doc:`/user_guide/config_reference/schema_explorer` -- user-facing
  schema viewer.

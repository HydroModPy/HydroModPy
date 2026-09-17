Exit codes
==========

Every :command:`hmp` verb maps its outcome to a typed exit code defined
in ``hydromodpy/cli/helpers.py``. The same mapping powers
``exit_code_for(exc)``, which routes Python exceptions to the matching
code. Scripts and CI gates can rely on the table below; new failure
categories reuse the 10..21 band before introducing new ranges.

.. list-table::
   :header-rows: 1
   :widths: 10 25 65

   * - Code
     - Name
     - Meaning
   * - 0
     - ``EXIT_OK``
     - Success.
   * - 1
     - ``EXIT_GENERIC``
     - Generic failure with no specific mapping.
   * - 2
     - ``EXIT_USAGE``
     - Invalid CLI usage: argparse rejected the call, or a job directory was
       named that does not exist or carries no ``request.json``.
   * - 10
     - ``EXIT_NOT_FOUND``
     - Missing file, workspace, simulation, or catalog row.
       Raised for ``FileNotFoundError``.
   * - 11
     - ``EXIT_SCHEMA_MISMATCH``
     - Catalog or lockfile schema does not match the running version, or a
       request targets a different major version of the capability.
   * - 12
     - ``EXIT_WRITE_CONFLICT``
     - Concurrent writer detected on the catalog or workspace.
   * - 13
     - ``EXIT_READ_ONLY``
     - Target opened read-only; the mutation was refused.
   * - 14
     - ``EXIT_CONFIG``
     - Invalid or missing TOML / Pydantic configuration.
   * - 15
     - ``EXIT_SOLVER_ERROR``
     - Solver (MODFLOW 6, MODFLOW-NWT, Boussinesq, GR4J) failed, or a terrain
       engine failed to serve what a capability asked of it.
   * - 16
     - ``EXIT_VALIDATION``
     - Data validation failed (units, ranges, schema constraints).
   * - 17
     - ``EXIT_CROSS_PROJECTS``
     - Operation crossed project boundaries (forbidden).
   * - 18
     - ``EXIT_BACKUP_FAILED``
     - Required backup step failed during a destructive action.
   * - 19
     - ``EXIT_MIGRATION_FAILED``
     - Workspace or catalog migration failed.
   * - 20
     - ``EXIT_AMBIGUOUS_REFERENCE``
     - A run reference matched several runs. Lengthen the id prefix or use
       the full name.
   * - 21
     - ``EXIT_CALIBRATION``
     - Calibration loop failed: objective evaluation or optimizer backend
       raised an unrecoverable error.
   * - 130
     - ``EXIT_SIGINT``
     - Interrupted by ``Ctrl+C`` (``KeyboardInterrupt``). POSIX
       convention (128 + SIGINT).

Exception mapping
-----------------

``hydromodpy.cli.helpers.exit_code_for(exc)`` returns the typed code
for an exception instance. ``KeyboardInterrupt`` always maps to 130;
``FileNotFoundError`` and an unresolved reference map to 10; an ambiguous
reference maps to 20. Domain exceptions defined in
``hydromodpy.core.exceptions`` (``SchemaVersionMismatchError``,
``WriteConflictError``, ``ReadOnlyError``, ``ConfigError``,
``ConfigMissingError``, ``SolverError``, ``DataError``,
``CrossProjectsError``, ``BackupFailedError``, ``MigrationFailedError``)
map to codes 11..19 respectively. ``CalibrationError`` (and its
``ObjectiveError`` / ``OptimizerError`` subclasses) maps to 21. The two
exceptions of the external-process boundary map with them: ``JobUsageError``
to 2 and ``CapabilityVersionMismatchError`` to 11. ``TerrainError`` and its
subclasses map to 15, beside the solvers: at a process boundary the terrain
engine *is* the geospatial backend. Any other exception falls back to
``EXIT_GENERIC`` (1).

A refused configuration document
--------------------------------

Every refusal of a configuration document leaves the config boundary as
``hydromodpy.core.exceptions.ConfigValidationError`` (code ``HMPY.E101``),
so ``hmp`` exits **14** and never 1. This covers the three mechanisms that
refuse a document: a Pydantic field fault, a refusal written by hand before
the model runs (a retired section, an unknown top-level section, a missing
``[workspace].project_root``), and a ``ValueError`` raised by a section
loader.

The exception carries the faults as data, not only as a sentence::

    from hydromodpy.config import HydroModPyConfig
    from hydromodpy.core.exceptions import ConfigValidationError

    try:
        HydroModPyConfig.from_toml("project.toml")
    except ConfigValidationError as exc:
        exc.to_dict()
        # {'type': 'urn:hmp:error:HMPY.E101',
        #  'code': 'HMPY.E101',
        #  'title': 'The configuration document failed validation.',
        #  'detail': '1 validation error(s) in project.toml: ...',
        #  'source': 'project.toml',
        #  'details': [{'pointer': '/geographic/dem_correction_type',
        #               'loc': 'geographic.dem_correction_type',
        #               'msg': 'Extra inputs are not permitted',
        #               'type': 'extra_forbidden',
        #               'line': 8}]}

``pointer`` is an RFC 6901 JSON Pointer into the document, which is what a
front end needs to highlight the offending field. ``line`` is present only
when the source file was readable and the locator found the token.

``to_dict()`` is defined on ``HydroModPyError``, so every typed exception
renders the same four members (``type``, ``code``, ``title``, ``detail``).
The ``urn:`` identifier resolves to nothing on purpose: no namespace is
registered, and an identifier that 404s is worse than one that never
promised to resolve.

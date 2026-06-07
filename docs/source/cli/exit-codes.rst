Exit codes
==========

Every :command:`hmp` verb maps its outcome to a typed exit code defined
in ``hydromodpy/cli/helpers.py``. The same mapping powers
``exit_code_for(exc)``, which routes Python exceptions to the matching
code. Scripts and CI gates can rely on the table below; new failure
categories will reuse codes 10..19 before introducing new ranges.

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
     - Invalid CLI usage (argparse rejected the call).
   * - 10
     - ``EXIT_NOT_FOUND``
     - Missing file, workspace, simulation, or catalog row.
       Raised for ``FileNotFoundError``.
   * - 11
     - ``EXIT_SCHEMA_MISMATCH``
     - Catalog or lockfile schema does not match the running version.
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
     - Solver (MODFLOW 6, MODFLOW-NWT, Boussinesq, GR4J) failed.
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
   * - 130
     - ``EXIT_SIGINT``
     - Interrupted by ``Ctrl+C`` (``KeyboardInterrupt``). POSIX
       convention (128 + SIGINT).

Exception mapping
-----------------

``hydromodpy.cli.helpers.exit_code_for(exc)`` returns the typed code
for an exception instance. ``KeyboardInterrupt`` always maps to 130;
``FileNotFoundError`` maps to 10. Domain exceptions defined in
``hydromodpy.core.exceptions`` (``SchemaVersionMismatchError``,
``WriteConflictError``, ``ReadOnlyError``, ``ConfigError``,
``ConfigMissingError``, ``SolverError``, ``DataError``,
``CrossProjectsError``, ``BackupFailedError``, ``MigrationFailedError``)
map to codes 11..19 respectively. Any other exception falls back to
``EXIT_GENERIC`` (1).

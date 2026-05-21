V1 Release Contract
===================

This page records the stable V1 surface and the intentional exclusions.
It is a product contract, not a roadmap.

Stable Python API
-----------------

.. list-table::
   :header-rows: 1
   :widths: 24 24 24 28

   * - Capability
     - Python API
     - CLI
     - TOML status
   * - Open project catalog
     - ``hmp.open``
     - CLI-only catalog browsing
     - not a TOML workflow
   * - Open V1 catalog facade
     - ``hmp.open_catalog``
     - ``hmp catalog``
     - not a TOML workflow
   * - Global index
     - ``hmp.index``
     - ``hmp workspace``
     - not a TOML workflow
   * - Run workflow
     - ``hmp.run``
     - ``hmp run``
     - ``simulation``, ``calibration``, ``overview``,
       ``comparison``, ``testbed``
   * - Calibration
     - ``hmp.calibrate``
     - ``hmp calibrate``
     - ``calibration``
   * - Pairwise comparison
     - ``hmp.compare_pair``
     - ``hmp report compare``
     - not a TOML workflow
   * - Mesh helper
     - ``hmp.mesh``
     - no dedicated stable verb
     - mesh-only public runs use ``simulation`` with a mesh process
   * - Read persisted variable
     - ``hmp.read``
     - Python-only
     - not a TOML workflow
   * - Audit prune
     - ``hmp.audit_prune``
     - ``hmp audit prune``
     - not a TOML workflow
   * - Doctor diagnostics
     - ``hmp.doctor``
     - ``hmp doctor``
     - not a TOML workflow

Python-only expert APIs
-----------------------

``Project`` is stable as the object-oriented facade. Its session-level
``sweep`` helper is Python-only in V1. ``workflow.mode = "sweep"`` is
not accepted by ``HydroModPyConfig`` or ``workflow.dispatch``.

Experimental or outside V1
--------------------------

- ``validity_frame``: experimental observability sidecars, no stable
  public API guarantee.
- Developer CLI commands under ``hmp dev``: diagnostics and local tools,
  not user-facing V1 workflows.
- User-managed draft examples: may document ideas, but they are not
  runnable V1 examples unless explicitly marked as such.

Lockfile
--------

``hydromodpy.lock`` is a best-effort reproducibility manifest in V1.
It is written when the data cache is available and the run path can
collect input fingerprints. A missing lockfile is a reproducibility
warning, not a failed run, unless a caller uses frozen replay.

Storage
-------

DuckDB is the canonical V1 SQL backend. The project catalog exposes a
port, but the product contract does not promise a non-DuckDB runtime
backend in V1. See :doc:`artifact-policy` for allowed sidecar formats.

Environment variables
---------------------

.. list-table::
   :header-rows: 1
   :widths: 28 20 52

   * - Variable
     - Status
     - Meaning
   * - ``HMP_WORKSPACE``
     - stable
     - Default workspace for catalog, workspace and run helpers.
   * - ``HMP_SET_*``
     - stable CLI
     - ``hmp run`` overrides using double underscores for nested keys.
   * - ``HMP_CACHE_HOME``, ``HMP_STATE_HOME``, ``HMP_BIN``
     - stable
     - Relocate machine cache, state index and solver binaries.
   * - ``HMP_AUTH_BACKEND``, ``HMP_USER``
     - stable
     - Operator identity for audit/privacy helpers.
   * - ``HMP_AUTO_MIGRATE``
     - stable
     - Set to ``0`` to block automatic schema migrations.
   * - ``HMP_PROJECT_ROOT``
     - test/dev
     - Overrides TOML project roots in test infrastructure. Not a user
       configuration API.
   * - ``HMP_TEST_*``, ``HMP_OUT_PATH``, ``HMP_COVERAGE``
     - test/dev
     - Pytest scratch roots, validation output roots and coverage flags.
   * - ``HMP_PANDERA_STRICT``, ``HMP_DETERMINISTIC_FETCHED_AT``
     - test/dev
     - Data-validation and deterministic sidecar diagnostics.
   * - ``HMP_WHITEBOX_*``, ``HMP_GMSH_VERBOSE``,
       ``HMP_MESH_TRACE_FILE``
     - diagnostics
     - Spatial and mesh debugging controls.
   * - ``HMP_DOC*``, ``HMP_SKIP_CONFIG_REFERENCE_GEN``
     - docs
     - Sphinx build and documentation-gallery controls.

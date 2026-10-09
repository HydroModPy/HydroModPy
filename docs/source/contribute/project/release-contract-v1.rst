V1 release contract
===================

This page records the stable V1 surface and the intentional exclusions.
It is a product contract, not a roadmap.

Stable Python API
-----------------

The table lists the verbs the contract covers. Every public name is in the
:doc:`generated Python reference </reference/python/index>`.


.. list-table::
   :header-rows: 1
   :widths: 24 24 24 28

   * - Capability
     - Python API
     - CLI
     - TOML status
   * - Open project catalog
     - ``hmp.open``
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
   * - Read persisted variable
     - ``hmp.read``
     - Python-only
     - not a TOML workflow
   * - Doctor diagnostics
     - ``hmp.doctor``
     - ``hmp doctor``
     - not a TOML workflow

Python-only expert APIs
-----------------------

``Project`` is stable as the object-oriented facade. A parameter sweep
is a Python-only loop over ``project.simulate(...)`` in V1.
``workflow.mode = "sweep"`` is not accepted by ``HydroModPyConfig`` or
``workflow.dispatch``.

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
backend in V1. See :ref:`artifact-policy` for allowed sidecar formats.

Environment variables
---------------------

The ``HMP_*`` variables the code reads, with their default and scope, are in
:doc:`../architecture/generated/environment`. The user-facing ones are part of
this contract. The ones for tests, diagnostics and the documentation build are
not.

Documentation Refresh
=====================

.. refresh-status:: daily_docs

.. refresh-status:: weekly_compute

This page records how the published documentation is refreshed and how to read
the small status badges shown on generated pages. The policy is intentionally
quiet: detailed refresh metadata lives here, while ordinary pages only expose a
compact green or red indicator when they depend on generated artifacts.

Current Status
--------------

.. refresh-status::

Badge Meaning
-------------

Green means that the last refresh attempt for the relevant artifact family
completed successfully. The compact badge only says ``up to date``.

Red means that the last refresh attempt failed. The page still shows the last
valid committed result, and the badge includes the last valid update date when
one has been recorded.

Grey is reserved for pages or artifact families that have no recorded refresh
status yet.

Refresh Cadence
---------------

Daily lightweight refresh
~~~~~~~~~~~~~~~~~~~~~~~~~

The lightweight documentation refresh is expected to run every night, around
03:30 in the Europe/Paris timezone.

It updates:

- Sphinx HTML generated from committed source files.
- The configuration reference generated from the current Pydantic models.
- Figure inventories and gallery index pages.
- Pages that can be regenerated only from committed artifacts.
- The refresh-status registry in ``docs/source/_static/refresh_status/``.

It does not update:

- MODFLOW, Boussinesq, PETSc, or calibration runs.
- Local outputs that have not been imported into committed documentation
  artifacts.
- Large testbed comparisons under ``examples/projects/**/outputs`` unless a
  documented import step has already committed their published summaries.

Weekly compute refresh
~~~~~~~~~~~~~~~~~~~~~~

The computed-artifact refresh is expected to run weekly, preferably on Sunday
morning when documentation latency is less disruptive.

It is responsible for:

- Analytical validation cases.
- XT3D before/after diagnostics.
- Calibration twin benchmarks.
- Declared testbed comparison artifacts that are part of the public gallery.

This refresh should be allowed to fail without blocking ordinary documentation
updates. When it fails, the docs keep serving the last valid committed
artifacts and the related status badge turns red.

Differential Update Rule
------------------------

Generated artifact pages should use a source fingerprint before recomputing.
The fingerprint should include:

- Input TOML files.
- Case scripts such as ``run_case.py``, ``comparison.py``, and ``plotting.py``.
- Relevant gallery manifests and summary JSON files.
- HydroModPy commit hash.
- Solver versions when solver binaries are involved.

If the fingerprint is unchanged and the expected artifacts exist, the workflow
can mark the case as ``skipped_unchanged`` and keep the previous artifacts. If
the fingerprint changed, or if an artifact is missing, the workflow should
regenerate that case and update its status entry.

Where Status Is Stored
----------------------

The visible badges read from:

``docs/source/_static/refresh_status/index.json``

Each entry records:

- the refresh family identifier;
- the last attempt date;
- the last successful date;
- the status, currently ``success``, ``failed``, or ``unknown``;
- the workflow name;
- a short human-readable message.

Generated case pages can either point at a broad family status, such as
``weekly_compute``, or at a more specific case status once per-case differential
refresh is enabled.

Publication Contract
--------------------

Read the Docs publishes what is committed. A local simulation run is not
published just because it exists on a workstation. It becomes part of the
published documentation only after an import or refresh step writes the
documentation artifacts, those artifacts are committed, and Read the Docs
successfully rebuilds the corresponding version.


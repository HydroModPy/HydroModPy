GitHub Actions workflows
========================

HydroModPy uses one main pull-request gate plus focused workflows for
documentation, solver-specific checks, dependency security, releases, and
scheduled suites. The workflow and job names are part of the developer
interface: a failing GitHub check should say which domain failed before a
contributor opens the logs.

Main CI gate
------------

``CI / Main Gate`` runs on every push and pull request targeting ``main`` or
``dev``. For a direct-push workflow, this is the main signal to read after
each push. It replaces the older split between ``CI Fast`` and ``Tests``.

.. list-table::
   :header-rows: 1
   :widths: 28 46 26

   * - Job name
     - Purpose
     - Failure usually means
   * - ``Quality / ruff``
     - Ruff lint and format checks.
     - Style, imports, formatting, or static lint regression.
   * - ``Security / gitleaks``
     - Secret scan over the repository checkout.
     - Token, password, key, or secret-like text committed.
   * - ``Architecture / layer matrix``
     - Strict import-layer tests under ``tests/unit/architecture/``.
     - Forbidden cross-layer dependency or private-module import.
   * - ``Tests / fast marker pyX.Y``
     - ``pytest -m fast`` on Python 3.11, 3.12, and 3.13.
     - Python-version compatibility or fast contract failure.
   * - ``Tests / unit py3.13``
     - Full unit tier on Python 3.13, with whitebox-heavy tests isolated.
     - Local API, class, function, or fixture regression.
   * - ``Tests / integration py3.13``
     - Integration tier after the unit tier succeeds.
     - Cross-module workflow or persisted-output contract regression.
   * - ``Regression / fast solvers py3.12``
     - Fast regression cases with MODFLOW-related binaries installed.
     - Solver-facing behavior changed unexpectedly.
   * - ``Package / wheel smoke py3.12``
     - Build wheel and sdist, install the wheel in a clean venv, run
       ``hmp doctor --json``.
     - Broken packaging metadata, console script, or runtime dependency.
   * - ``Typing / mypy baseline py3.12 (advisory)``
     - Non-blocking type-check baseline.
     - Type debt changed. Treat as useful signal, not a merge blocker yet.

Specialized pull-request workflows
----------------------------------

These workflows run only when their inputs change, or when started manually.

.. list-table::
   :header-rows: 1
   :widths: 24 38 38

   * - Workflow
     - Trigger
     - Purpose
   * - ``Docs / Sphinx``
     - Documentation, package source, project metadata, README, or
       contributor docs change.
     - Build ``make -C docs html-strict`` and upload rendered HTML.
   * - ``Docs / Gallery Sync``
     - Gallery tools, validation reports, gallery examples, or committed
       gallery artifacts change.
     - Verify committed gallery artifacts match ``tools.doc_gallery``.
   * - ``Performance / Benchmarks``
     - Performance tests, benchmark comparator, project metadata, or package
       source change.
     - Compare benchmark pairwise ratios with the committed baseline.
   * - ``Docker / Build Smoke``
     - Dockerfile, project metadata, package source, or Docker workflow change.
     - Build the image and check CLI entrypoints.
   * - ``Solver / PETSc Smoke``
     - Boussinesq/PETSc code, related tests, validation shared data, or PETSc
       smoke script change.
     - Validate the conda-forge PETSc stack and Boussinesq smoke suite.
   * - ``CI / Workflow Lint``
     - GitHub Actions workflow or local action files change.
     - Run ``actionlint`` before broken workflow YAML reaches a branch.
   * - ``Security / Dependency Audit``
     - Dependency metadata changes, weekly schedule, or manual dispatch.
     - Run ``pip-audit`` against declared Python dependencies.

Scheduled workflows
-------------------

Scheduled workflows keep expensive or noisy checks out of the per-commit
path.

``Nightly / Linux Suites`` checks ``main`` and ``dev`` every night. It runs
extensive regression tests, validation tests excluding PETSc, and integration
coverage.

``Weekly / Cross Platform`` runs on the repository default branch every
Sunday. It checks the supported Python versions across Linux, macOS, and
Windows, then runs Linux end-to-end and full regression jobs.

``Docs / Nightly Refresh`` refreshes generated documentation artifacts on
``main`` and ``dev`` and pushes only those generated outputs when they
change.

``Solver / PETSc Smoke`` also has a Monday scheduled run because PETSc and
``petsc4py`` come from a separate conda-forge environment.

Release workflow
----------------

``Release / PyPI`` is isolated from the pull-request gate. It runs on
``v*.*.*`` tags or manual dispatch, builds distributions, generates a
CycloneDX SBOM, uploads to PyPI through Trusted Publishing, then creates the
GitHub release.

Reading failures
----------------

Use the first path component in the job name as the triage entry point:

- ``Quality``: run ``ruff check .`` and ``ruff format --check .`` locally.
- ``Architecture``: inspect imports against
  ``tests/unit/architecture/layer_matrix.yaml`` before changing code.
- ``Tests``: reproduce the tier named in the check, not the whole suite.
- ``Regression`` or ``Validation``: check solver binaries and numerical
  tolerances before changing expected results.
- ``Docs``: reproduce with ``make -C docs html-strict``. The Makefile keeps
  Sphinx parallel with ``-j auto``.
- ``Security``: never paste secrets into logs or issues. Rotate the leaked
  credential before removing it from the tree.
- ``Performance``: inspect the uploaded benchmark report before deciding
  whether the drift is a real regression or runner noise.

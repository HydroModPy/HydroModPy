Test Inventory
==============

This page is a compact map of the current HydroModPy pytest suite. It
complements :doc:`test-families-and-quality-roles`: that page explains
what each test family means, while this page answers "what do the
thousands of collected tests cover today?"

Snapshot method
---------------

The counts below were collected from the repository root with:

.. code-block:: bash

   python -m pytest --collect-only -q -o addopts= \
     --ignore=tests/integration/test_run_dataset_xugrid.py \
     --ignore=tests/unit/test_data_schemas.py

The two ignored files require optional dependencies that were missing in
the local Python environment used for this snapshot: ``xugrid`` and
``pandera``. A fully provisioned development environment may therefore
collect a few more tests.

Collected test count: **3368**.

Runtime envelope
----------------

The table below records the current execution budget rather than a
precise benchmark. Local runtime depends heavily on solver binaries,
native geospatial libraries, xdist parallelism, and whether coverage is
enabled. The authoritative limits live in ``tests/conftest.py`` and in
the GitHub Actions workflow files.

.. list-table::
   :header-rows: 1
   :widths: 20 20 28 32

   * - Family
     - Default per-test timeout
     - CI budget
     - Main CI source
   * - ``unit``
     - 60 s
     - 25 min on push/PR; part of 45 min cross-OS weekly matrix
     - ``.github/workflows/main-ci.yml`` and
       ``.github/workflows/ci-weekly.yml``
   * - ``integration``
     - 300 s
     - 30 min on push/PR after unit tests; 30 min nightly coverage
     - ``.github/workflows/main-ci.yml`` and
       ``.github/workflows/ci-nightly.yml``
   * - ``regression`` fast
     - 300 s
     - 25 min on push/PR; part of 45 min cross-OS weekly matrix
     - ``.github/workflows/main-ci.yml`` and
       ``.github/workflows/ci-weekly.yml``
   * - ``regression`` extensive
     - 300 s
     - 60 min nightly on Linux
     - ``.github/workflows/ci-nightly.yml``
   * - ``validation`` non-PETSc
     - 900 s
     - 45 min nightly on Linux; analytical subset in weekly cross-OS
       matrix
     - ``.github/workflows/ci-nightly.yml`` and
       ``.github/workflows/ci-weekly.yml``
   * - ``validation`` PETSc
     - 900 s
     - 60 min Linux smoke workflow
     - ``.github/workflows/petsc-smoke.yml``
   * - ``e2e``
     - 1800 s
     - 60 min weekly on Linux
     - ``.github/workflows/ci-weekly.yml``

Notes:

- **Default per-test timeout** is the maximum wall-clock time allowed
  for one collected pytest item before ``pytest-timeout`` stops it. It
  is not an expected runtime. These defaults are applied by
  ``tests/conftest.py`` from the test path: unit tests get a short
  timeout, validation and e2e tests get longer limits.
- **CI budget** is the maximum wall-clock time allowed for the whole
  GitHub Actions job. It includes environment setup, dependency
  installation, solver binary installation when needed, the tests
  themselves, coverage reporting, and artifact upload.
- **Main CI source** is the workflow file where that automated signal is
  declared. Open it when you need the exact command, platform, Python
  version, schedule, or timeout.

Platform signal
---------------

HydroModPy does not currently claim that every test in every family runs
on every operating system. The CI matrix is the practical contract:

.. list-table::
   :header-rows: 1
   :widths: 24 30 46

   * - Platform signal
     - Suites
     - Notes
   * - Push / pull request on Linux
     - Quality, architecture, fast marker suite, unit, integration,
       fast regression, wheel smoke, secret scan, advisory mypy
     - Runs on ``ubuntu-latest`` through ``main-ci.yml``. This is the
       main blocking signal for routine changes.
   * - Nightly Linux
     - Extensive regression, integration, validation excluding PETSc
     - Covers slower tiers that are too expensive for every push.
   * - Weekly Linux, macOS, Windows
     - Unit tests, fast regression, analytical validation excluding
       PETSc
     - This is the main cross-platform signal. It does not run the full
       validation, extensive regression, or e2e inventory on Windows.
   * - Weekly Linux only
     - End-to-end tests and full regression
     - Heavy user-facing scenarios and deeper workflow goldens.
   * - PETSc smoke
     - PETSc-tagged Boussinesq validation subset
     - Linux-only by design. ``tests/conftest.py`` skips ``petsc``
       tests on non-Linux platforms or when ``petsc4py`` is absent.

Coverage index
--------------

The live test-coverage index is externalized to Codecov rather than
committed as a changing number in this repository. The current public
entry points are:

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - Where
     - What it gives you
   * - `Codecov badge SVG <https://codecov.io/gh/HydroModPy/HydroModPy/branch/dev/graph/badge.svg>`__
     - The compact live badge used by ``README.md``. It is useful for a
       quick project-level percentage, but it does not show file-level
       details.
   * - `Codecov dashboard <https://codecov.io/gh/HydroModPy/HydroModPy/tree/dev>`__
     - The detailed hosted view: project trend, file-level coverage,
       pull-request diff coverage, and per-flag breakdowns when uploads
       are available.
   * - Codecov pull-request comment
     - The review-time summary when a pull-request workflow uploads
       coverage. The current optimized gate keeps coverage on scheduled
       suites rather than every PR.
   * - Local ``coverage report --show-missing``
     - The direct local view after running tests with coverage. It
       prints missing lines per Python file.
   * - Local ``coverage html``
     - A browsable local HTML report under ``htmlcov/`` after a coverage
       run.

In other words, the repository stores the **rules** for coverage
collection and upload, while Codecov stores the latest **measured
index**.

Coverage is configured in two layers:

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - File
     - Role
   * - ``pyproject.toml``
     - Defines what counts as HydroModPy source code for Coverage.py.
       The ``[tool.coverage.run]`` section lists the packages measured
       by coverage, for example ``hydromodpy.core``,
       ``hydromodpy.config``, ``hydromodpy.solver``, and
       ``hydromodpy.workflow``. It also excludes files that should not
       affect the coverage percentage, such as examples, docs, test
       files, validation cases, and bundled example/case folders.
   * - ``pyproject.toml``
     - Defines how the local text report is rendered. The
       ``[tool.coverage.report]`` section enables missing-line output,
       skips empty files, and ignores standard non-executable patterns
       such as ``if TYPE_CHECKING:`` or ``raise NotImplementedError``.
   * - ``codecov.yml``
     - Defines how Codecov interprets uploaded ``coverage.xml`` files:
       project-level threshold, patch-level threshold, ignored paths,
       and the pull-request comment layout.
   * - ``codecov.yml``
     - Defines **flags**, which are labels attached to CI uploads. They
       let the dashboard distinguish coverage coming from ``unit``,
       ``regression-fast``, ``regression-extensive``, ``validation``,
       ``integration``, and ``e2e`` jobs.

The usual local commands are:

.. code-block:: bash

   python -m pytest tests/unit --cov=hydromodpy --cov-report=
   coverage report --show-missing
   coverage html

Automatic updates already happen through CI:

.. list-table::
   :header-rows: 1
   :widths: 25 35 40

   * - Workflow
     - Uploaded flags
     - Trigger
   * - ``ci-nightly.yml``
     - ``regression-extensive``, ``validation``, ``integration``
     - Nightly schedule and manual dispatch.
   * - ``ci-weekly.yml``
     - ``e2e``
     - Weekly schedule and manual dispatch.

Because Codecov flags use ``carryforward: true``, the dashboard can keep
a coherent project-level view even when only scheduled coverage jobs run.
If a static coverage number is later needed in the generated HTML docs,
prefer a small docs-refresh step that reads the Codecov API and commits a
generated JSON summary on ``dev`` only. Avoid having pull-request CI push
coverage files back to the branch: it creates noisy commits and is
fragile for forks and protected branches.

By test family
--------------

.. list-table::
   :header-rows: 1
   :widths: 20 15 65

   * - Family
     - Tests
     - What the family mostly covers
   * - ``unit``
     - 3024
     - Local contracts: schemas, helpers, adapters, data managers,
       solvers, mesh utilities, calibration primitives, result stores.
   * - ``regression``
     - 128
     - Known workflow outputs, public API consistency, golden
       signatures, and solver intercomparison summaries.
   * - ``validation``
     - 118
     - Analytical benchmarks, numerical stress cases, MMS checks, and
       calibration twin experiments.
   * - ``integration``
     - 82
     - Cross-package composition without golden references: CLI,
       results, ML access, calibration bridges, and workflow plumbing.
   * - ``e2e``
     - 16
     - Full user-facing scenarios such as add/export round-trips,
       resume after interrupt, and complete simulation cycles.

Largest unit-test areas
-----------------------

.. list-table::
   :header-rows: 1
   :widths: 26 14 60

   * - Area
     - Tests
     - Main protection role
   * - ``data_managers``
     - 543
     - Custom and provider-backed data loading, validation,
       autoscan, catalog handling, unit conversion, and data-source
       contracts.
   * - ``solver``
     - 312
     - MODFLOW-NWT, MODFLOW 6, PETSc/Boussinesq, boundary-condition
       translation, output adapters, solver registries, and numerical
       contracts.
   * - ``simulation``
     - 262
     - Simulation catalog APIs, result stores, exports, comparison
       metrics, run grids, observations, and post-run access.
   * - ``calibration``
     - 259
     - Objective construction, candidate materialization, optimizer
       orchestration, parameter handling, cache behaviour, and CLI
       session state.
   * - ``mesh``
     - 219
     - Cartesian grids, Gmsh grids, conformal meshing, geometry
       constraints, field discretization, and reference mesh cases.
   * - ``launchers``
     - 216
     - TOML-to-workflow entry points, simulation/comparison launchers,
       batch launchers, CLI wiring, and error paths.
   * - ``analysis``
     - 118
     - Comparison metrics, web-report sections, audit payloads,
       experiment configuration, and analysis exports.
   * - ``config``
     - 83
     - TOML loading, schema export, units round-trips, native dispatch,
       error location, and cross-section validation.

Validation-test areas
---------------------

.. list-table::
   :header-rows: 1
   :widths: 26 14 60

   * - Area
     - Tests
     - Main protection role
   * - ``analytical``
     - 92
     - Solver-backed comparisons against closed-form or
       semi-analytical groundwater-flow references.
   * - ``numerical``
     - 12
     - PETSc/Boussinesq stress cases and multi-backend robustness cases
       without a clean closed-form target.
   * - ``calibration``
     - 11
     - Synthetic twin experiments that check whether the inverse chain
       can recover known parameters.
   * - ``mms``
     - 3
     - Manufactured-solution checks for expected convergence behaviour.

Regression-test areas
---------------------

.. list-table::
   :header-rows: 1
   :widths: 26 14 60

   * - Area
     - Tests
     - Main protection role
   * - ``test_api_public_consistency.py``
     - 97
     - Public facade and exported symbol consistency.
   * - ``fast``
     - 25
     - Routine workflow goldens and compact intercomparison checks.
   * - ``extensive``
     - 5
     - Heavier workflow goldens for pre-merge or pre-release checks.
   * - ``toml_io``
     - 1
     - TOML I/O regression coverage.

How to use this page
--------------------

- Start with :doc:`test-families-and-quality-roles` when you need to
  interpret a failed family.
- Use this page when you need to understand where most of the suite's
  coverage lives before changing a subsystem.
- Use :doc:`../how-to/add-a-test` when deciding where a new test should
  be placed.
- Use ``tests/validation/README.md`` and ``validation_cases/README.md``
  for case-by-case scientific validation details.
- Use ``tests/regression/README.md`` for golden-reference maintenance.

Potential next step
-------------------

This page is intentionally static and lightweight. If the suite keeps
growing, the natural next step is a small ``tools.doc_tests`` generator
that writes this page plus a downloadable JSON or CSV inventory from
``pytest --collect-only``. The generated artifact should be committed
and checked with a ``--check`` mode rather than regenerated during every
Sphinx build.

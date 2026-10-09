Reading a failing check
=======================

HydroModPy has one pull-request gate and a set of focused workflows under
``.github/workflows/``. A job name starts with the domain that failed, so a red
check says where to look before you open the log. The table of workflow files,
triggers and jobs is generated from the YAML and never drifts:
:doc:`../architecture/generated/ci`. This page is the triage: what each domain
means and how to reproduce it.

The main gate
-------------

``CI / Main Gate`` (``main-ci.yml``) runs on every push and pull request to
``main`` or ``dev``. It is the signal to read after each push. Its jobs, in the
order they matter:

- ``Quality / ruff`` and ``Security / gitleaks`` are the style and the secret
  scan, the same as the pre-commit hooks.
- ``Architecture / layer matrix`` runs ``tests/unit/architecture/``.
- ``Characterization / produced run`` runs one real ``hmp run`` of the example 00
  aquifer and reads back only what it left on disk.
- ``Tests / fast marker``, ``Tests / unit`` and ``Tests / integration`` are the
  pytest tiers. Whitebox-backed tests run in their own serial step.
- ``Regression / fast solvers`` runs the fast regression cases with solver
  binaries installed.
- ``Package / wheel smoke`` builds the wheel and the sdist, installs the wheel in
  a clean environment and runs ``hmp doctor --json``.
- ``Typing / mypy baseline`` is advisory: it does not block a merge.

Other workflows
---------------

These run when their inputs change, on a schedule, or on demand.

- ``Docs / Sphinx`` (``docs.yml``) builds the site strictly, then runs
  ``check_page`` and ``check_site``, then fails if the build changed a tracked
  file under ``docs/source``.
- ``Docs / Deploy Pages (multi-version)`` (``docs-deploy-pages.yml``) builds one
  branch or tag and publishes it to its own folder of ``docs.hydromodpy.fr``.
- ``Performance / Benchmarks`` compares pairwise benchmark ratios to the committed
  baseline.
- ``Docker / Build Smoke`` builds the image and checks the entry points.
- ``Solver / PETSc Smoke`` validates the conda-forge PETSc stack and the
  Boussinesq smoke suite. It also has a weekly run.
- ``CI / Workflow Lint`` runs ``actionlint`` on workflow files.
- ``Security / Dependency Audit`` runs ``pip-audit`` on pull requests that change
  dependencies, and weekly.
- ``Nightly / Linux Suites`` runs the extensive regression, the validation without
  PETSc and the integration coverage on ``main`` and ``dev``.
- ``Weekly / Cross Platform`` runs the supported Python versions on Linux, macOS
  and Windows, the end-to-end tier and the full regression.
- ``Weekly install & examples (v1.0)`` tests the install and the examples of the
  frozen v1.0 branch.
- ``Release / PyPI`` (``publish.yml``) runs on a ``v*.*.*`` tag. See
  :doc:`../architecture/how-to/cut-a-release`.

Reproduce a failure
-------------------

Use the first word of the job name.

``Quality``
   ``ruff check --fix <files>`` and ``ruff format <files>``.

``Security``
   For ``gitleaks``, never paste the secret in a log or an issue. Rotate the
   credential first, then remove it from the tree. For ``pip-audit``, read the
   advisory and the pinned range in ``pyproject.toml``.

``Architecture``
   ``python -m pytest tests/unit/architecture -q``. The failing test names the
   rule. :doc:`../architecture/how-to/fix-an-architecture-gate` says what to do for
   each one.

``Characterization``
   ``python -m pytest tests/characterization -q`` with the MODFLOW-NWT binary
   installed (``hmp install-binaries --subset mfnwt``). The tier holds strict
   ``xfail`` cases: one that starts to pass fails the job, which means a claim of
   the code is now honoured and the marker must go.

``Tests``
   Reproduce the tier and the Python version named in the check, not the whole
   suite. For a hang or a dead worker, see the Whitebox rule in
   :ref:`run-the-tests`.

``Regression`` and ``Validation``
   Check the solver binaries and the tolerances before touching an expected
   value. A regression failure says the workflow changed, not that it became
   wrong.

``Docs``
   ``make -C docs html-strict``, then ``python -m tools.docs.check_page`` and
   ``python -m tools.docs.check_site docs/build/html``. A "generated file is
   stale" error means the build rewrote a tracked file: run the build locally and
   commit the result. See :doc:`../documentation/how-the-docs-are-built`.

``Performance``
   Read the uploaded benchmark report before deciding whether the drift is real or
   runner noise.

``CI``
   ``actionlint .github/workflows/<file>.yml`` reports the line of a YAML error.

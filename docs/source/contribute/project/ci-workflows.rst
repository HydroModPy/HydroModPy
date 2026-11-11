Reading a failing check
=======================

HydroModPy has one pull-request gate and a set of focused workflows under
``.github/workflows/``. A job name starts with the domain that failed, so a red
check says where to look before you open the log. The table of workflow files,
triggers and jobs is generated from the YAML and never drifts:
:doc:`../architecture/generated/ci`. This page is the triage: what each domain
means and how to reproduce it. The workflows are the one place that holds the test
commands, and ``tools/ci/local.py`` replays their Linux steps on your machine.

The main gate
-------------

``CI / Main Gate`` (``main-ci.yml``) runs on every push and pull request to
``main`` or ``dev``. It is the signal to read after each push. Its jobs, in the
order they matter:

- ``Quality / ruff`` and ``Security / gitleaks`` are the style and the secret
  scan, the same as the pre-commit hooks.
- ``Architecture / layers, surface and two threads`` runs
  ``tests/unit/architecture/``: the layer matrix, the run layouts, the public
  surface, the code rules and the gate that plays two runs in two threads of one
  process.
- ``Characterization / produced run`` runs one real ``hmp run`` of the example 00
  aquifer and reads back only what it left on disk.
- ``Tests / fast marker`` runs the ``fast`` tests on Python 3.11, 3.12 and 3.13,
  then the port tests with every solver binary installed and
  ``HMP_REQUIRE_BINARIES`` set, so a missing binary fails instead of skipping.
- ``Tests / unit`` runs the docstring examples, the unit tier, the process tests
  and the tests that reach the mesh and the calibration, under branch coverage.
  Tests marked ``whitebox`` run in their own serial step.
- ``Tests / scenarios`` plays the small synthetic projects of ``tests/scenarios``
  once each, in parallel and under the same coverage. Their ``python -m
  hydromodpy`` children count through ``patch = ["subprocess"]`` of
  ``pyproject.toml``.
- ``Coverage / floors per sub-package`` combines the data of the two jobs above
  and runs ``python tools/ci/coverage_floors.py check
  tools/ci/coverage_floors.toml``. The table holds one floor for each
  sub-package of ``hydromodpy/`` and one for the modules at the top of each
  package. It fails on a floor missed, on a sub-package without a line and on a
  line that names a path the tree no longer has. The floors only go up:
  ``coverage_floors.py measure tools/ci/coverage_floors.toml --write`` raises
  each one to half a point under the measure. A floor goes down only when files
  enter or leave its sub-package, with the reason in a comment on its line.
- ``Proof / tests removed lose nothing`` runs when a change removes test
  functions. ``tools/ci/proof.py select`` finds the removed functions, the
  modules they stood for and the tests that import those modules, and
  ``proof.py prove`` hands them to ``tools/ci/removal_proof.py check``. The
  check measures both sides and fails when a covered line, a covered branch or a
  killed mutant of those modules is lost. A loss in another module is listed as
  outside the bound and does not fail, because a test outside the measure may
  run that line. Exit code 0 means proved, 1 a loss
  named in ``proof/report.json``, 2 a refusal. It refuses a change that also
  edits ``hydromodpy/``, because the proof compares the same library code: remove
  the tests in a change of their own. A pull request is one change against its
  base. A push is proved commit by commit with ``proof.py range``, so a commit
  that only removes tests passes beside a commit that only edits the library.
  It also refuses a proof whose mutants
  would take more than 45 minutes: split the change, and the weekly package
  proof takes the rest. A push that removes no test ends in under a minute.
- ``Tests / integration`` runs ``tests/integration`` after the unit job.
- ``Regression / fast solvers`` runs the fast regression cases with solver
  binaries installed.
- ``Package / wheel smoke`` builds the wheel and the sdist, installs the wheel in
  a clean environment on Python 3.11, 3.12 and 3.13, and runs
  ``hmp doctor --format json``.
- ``Package / example catalog`` runs ``tools/ci/check_example_catalog.py``, which
  hashes every file ``hydromodpy/project/examples/catalog.toml`` names.
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
- ``Docker / Build Smoke`` builds the image with the tag ``ci`` and checks the entry points:
  ``hmp --help``, ``hmp --version`` and ``python -m hydromodpy_server --help``.
  Then it writes the ``nwt`` island of ``tests/scenarios/factory.py``, runs it in
  the image, checks that ``provenance.json`` seals the image digest, and replays
  it with ``hmp replay <run> --strict`` in the same image. The replay must be
  ``bit``. On a ``v*.*.*`` tag, the ``publish`` job pushes the image to
  ``ghcr.io`` with the version as its tag, and as ``latest`` when the version is
  not a pre-release. The digest goes to the job summary and to the
  ``image-digest`` artifact, and the same run and replay play on the published
  image pulled by its digest.
- ``Solver / PETSc Smoke`` validates the conda-forge PETSc stack and the
  Boussinesq smoke suite. It also has a weekly run.
- ``CI / Workflow Lint`` runs ``actionlint`` on workflow files.
- ``Security / Dependency Audit`` runs ``pip-audit`` on pull requests that change
  dependencies, and weekly.
- ``Nightly / Linux Suites`` runs the extensive regression, the validation without
  PETSc and the integration coverage on ``main`` and ``dev``.
- ``Weekly / Cross Platform`` runs the supported Python versions on Linux, macOS
  and Windows, the end-to-end tier and the full regression. It has three more
  jobs.
  ``Weekly / frozen MODFLOW 6 gmsh run and its tolerance`` replays the frozen run
  of ``tests/regression/frozen_replay`` with one BLAS thread, then with four. Each
  replay writes its class and its field-scale gaps to the file
  ``HMP_REPLAY_REPORT`` names, and the processor and the numpy build go beside
  them in the ``tolerance-<run id>`` artifact. The job fails unless both replays
  are ``bit``. A red here on a new processor is a measure, and the tolerance
  class is written by hand from the artifact.
  ``Weekly / package proof`` runs ``proof.py week``: each commit of the last seven
  days that removes tests is proved against its parent at the package scope,
  300 minutes in all. A commit that also edits ``hydromodpy/`` is listed as
  changed, a commit past the budget as left.
  ``Weekly / Windows server path and two processes`` runs on ``windows-latest``
  with ``HMP_REQUIRE_WINDOWS`` set. It runs every test marked ``windows``, so a
  Windows proof that skips fails the job. Then it runs the server tests, the
  process tests, the HTTP scenario, the scenario of two runs in two processes
  and the two-thread gate.
- ``Weekly / dependencies`` installs the direct dependencies at their lower bounds
  and with no upper cap, and runs the tiers that read stored files.
- ``Weekly / Install`` installs the wheel and the source tree on each Python and
  on each OS, and runs ``hmp doctor``. Only Linux blocks.
- ``Release / PyPI`` (``publish.yml``) runs on a ``v*.*.*`` tag. It starts with
  a gate: the tagged commit is on ``main`` or ``dev``, its ``CI / Main Gate`` run
  passed and the example catalog matches the tree. It tests the wheel on Python
  3.11, 3.12 and 3.13 before it uploads. See
  :doc:`../architecture/how-to/cut-a-release`.

Reproduce a failure
-------------------

``python tools/ci/local.py run --job <job> --out <dir>`` replays the Linux,
Python 3.13 steps of one job as the workflow writes them, with ``python`` set to
the interpreter that runs the script. Each step writes ``<dir>/<job>__<step>.log``
and one line ``<job>/<step> <code>`` in ``<dir>/status``.
``python tools/ci/local.py list`` prints every step: the ones it plays, and the
others with the reason they are not played locally (an install, an action, Docker,
another system or Python version, a GitHub expression). The module docstring of
``tools/ci/local.py`` gives the rules. Then use the first word of the job name.

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
   the code is now honored and the marker must go.

``Tests``
   Reproduce the tier and the Python version named in the check, not the whole
   suite. For a hang or a dead worker, see the Whitebox rule in
   :ref:`run-the-tests`. A test marked ``windows`` skips outside Windows. Set
   ``HMP_REQUIRE_WINDOWS=1`` on Windows to make such a skip fail, as the weekly
   Windows job does.

``Coverage``
   Run ``unit`` and ``scenarios`` through ``local.py``, then the ``coverage`` job:
   ``python tools/ci/local.py run --job unit --job scenarios --job coverage
   --out <dir>``. Each failing line reads ``<key> <measure> < <floor>``. Add tests
   for the sub-package it names. Lower a floor only when files entered or left
   the sub-package, and write the reason on its line.

``Proof``
   Download the ``proof`` artifact and read ``report.json``: it names each lost
   line, branch or mutant by module. To replay it, run
   ``python tools/ci/proof.py select --base <sha> --head <sha> --work <dir>
   --out <dir>/selection.json``, then ``python tools/ci/proof.py prove
   <dir>/selection.json --work <dir> --out <dir>/report.json --mutmut <python>``,
   where ``<python>`` has ``mutmut==3.8.0``. For a push, run ``python
   tools/ci/proof.py range --base <sha> --head <sha> --work <dir> --out
   <dir>/report.json --mutmut <python>`` instead. Keep the test that stood alone for
   the lost line, or write one that covers it.

``Regression`` and ``Validation``
   Check the solver binaries and the tolerances before touching an expected
   value. A regression failure says the workflow changed, not that it became
   wrong.

``Docker``
   The play and replay step runs ``hmp run project.toml`` from ``/project``, then
   ``hmp replay runs/nwt --strict``. Run the same two commands on the ``nwt``
   island of ``tests/scenarios/factory.py`` outside the image first. A replay
   that is not ``bit`` in the same image is a fault of the run, not of the runner.

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

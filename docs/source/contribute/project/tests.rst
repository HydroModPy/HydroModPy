Tests
=====

HydroModPy splits tests into families because they answer different questions.
This page is the map of those families, the routine commands, and the family to
consult when a failure has to be read. The counts per family and per area are
generated from the suite: :doc:`../architecture/generated/tests`. To write a
test, see :doc:`../architecture/how-to/add-a-test`.

For the architectural split between reusable benchmark logic
(``validation_cases/``) and pytest-facing assertions
(``tests/validation/``), see :ref:`tests-validation-split` below.

Quality ladder
--------------

.. list-table::
   :header-rows: 1
   :widths: 14 26 30 30

   * - Family
     - Main question
     - Typical scope
     - Routine command
   * - ``unit``
     - Does one local function, class, or schema behave correctly?
     - Isolated Python logic, local contracts, small fixtures.
     - ``python -m tools.dev test unit``
   * - ``integration``
     - Do several subsystems still cooperate?
     - Cross-module workflows without golden files.
     - ``pytest tests/integration -q``
   * - ``e2e``
     - Can one user-facing scenario complete from start to finish?
     - CLI / workspace lifecycle, export-import, resume cycles.
     - ``pytest tests/e2e -q``
   * - ``regression`` (fast)
     - Did a known workflow output drift?
     - Full workflows compared to committed golden signatures.
     - ``python -m tools.dev test regression --fast``
   * - ``regression`` (extensive)
     - Same, with heavier fixtures.
     - Wider workflow coverage; pre-merge / pre-release.
     - ``python -m tools.dev test regression --extensive``
   * - ``regression`` (frozen replay)
     - Does a stored run still replay bit for bit?
     - One frozen MODFLOW 6 run on triangles, replayed from a copy without
       gmsh. The weekly job replays it on another processor.
     - ``pytest tests/regression/frozen_replay -q``
   * - ``processes``
     - Do several processes on one folder leave it whole?
     - Locks, version claims, stores and server jobs tried by real
       ``spawn`` children, on Linux and Windows.
     - ``pytest tests/processes -q``
   * - ``validation`` (analytical)
     - Does the numerical result match a trusted reference?
     - Closed-form, semi-analytical, or stress benchmarks.
     - ``python -m tools.dev test validation --fast`` / ``--steady`` / ``--transient``
   * - ``validation`` (MMS)
     - Does the discrete scheme converge as theory predicts?
     - Manufactured solutions, refinement studies.
     - ``pytest tests/validation/mms -q``
   * - ``validation`` (numerical)
     - Robustness on cases without a clean closed form.
     - Multi-backend or PETSc-backed stress cases.
     - ``pytest tests/validation/numerical -q`` / ``pytest -m petsc -q``
   * - ``validation`` (calibration twin)
     - Can the inverse chain recover a known synthetic truth?
     - Parameter materialization, optimizer orchestration, recovery
       metrics.
     - ``pytest tests/validation/calibration -q``
   * - ``characterization``
     - Does one real run leave on disk what a stranger can read back?
     - One ``hmp run`` of a committed example, read only through the file
       formats a reader would use. Five strict ``xfail`` cases record claims
       the code makes and does not yet honor.
     - ``pytest tests/characterization -q``
   * - ``ports``
     - Do the implementations of a port honor the same behavior?
     - One file per port registry, parametrized on its names: solver, data
       source, terrain, mesh, optimizer, evaluator, figure and export. A case
       that cannot run here is a skip that says why.
     - ``pytest tests/ports -q``
   * - ``refusals``
     - Is a wrong input refused with its class, its code and a sentence that
       says what to do?
     - Tables of refused forms, combinations, sections, seals and data, and the
       exit code of every error category.
     - ``pytest tests/refusals -q``
   * - ``performance``
     - Did a benchmark drift against the committed baseline?
     - ``pytest-benchmark`` micro-benchmarks of the storage wrappers.
     - ``pytest tests/performance -q``
   * - ``solver_sanity``
     - Is the external solver itself correct?
     - MODFLOW vs Theis, Hantush, Ogata-Banks; flopy direct models.
     - ``pytest -m solver_sanity -q``
   * - ``validation_cases``
     - Can one benchmark be run outside pytest?
     - Reusable runners, figure-first diagnosis, report refresh.
     - ``python -m validation_cases.run_cases ...``

The split keeps four concerns separable: software correctness,
workflow stability, numerical consistency, and scientific validity.

Practical notes:

- ``python -m tools.dev test`` wraps the unit, regression, and validation suites. It runs
  from a source checkout, because ``tools/`` is not in the wheel.
- ``pytest`` is the direct entry point for the integration, e2e, MMS,
  characterization, ports, refusals and marker-based subsets.
- Run in parallel with the rules of :ref:`run-the-tests`.
- The PETSc subset is Linux-only. On Windows, run it through WSL via
  ``install/enter_wsl_dev.sh``.

What each family covers
-----------------------

Unit tests (``tests/unit/``) protect Pydantic schemas, helpers,
adapters, planners, and small runtime contracts. They do not exercise
launcher behavior or persisted outputs.

Port tests (``tests/ports/``) hold one file per port registry,
parametrized on the names the registry serves, so a new backend, engine,
source or figure is tested without naming it. A case that cannot run on this
machine is a skip that the object under test declares, such as a missing
solver binary.

Refusal tests (``tests/refusals/``) are tables. Each row is one wrong input,
the class it raises, its ``HMPY`` code and a fragment of the sentence that
says what to do. A table over a closed set, such as the retired keys or the
error categories, checks that its rows equal that set.

Integration tests (``tests/integration/``) exercise realistic
workflows without relying on golden datasets, catching boundary
mistakes between configuration, orchestration, catalog, and post-run
layers. They do not check long-term output stability.

End-to-end tests (``tests/e2e/``) verify a full user-visible scenario:
project creation roundtrips, export-import, full simulation or
calibration cycles, restart and resume.

Regression tests (``tests/regression/{fast,extensive}/``) compare
current outputs to committed signatures under
``tests/regression/reference/golden_references/``. A failure means
*the workflow changed*; it does not automatically mean *the workflow
became wrong*.

Scientific validation tests (``tests/validation/``) compare
solver-backed or calibration-backed results to trusted references.
Subfamilies:

- *analytical*: closed-form / semi-analytical comparisons.
- *MMS*: discrete convergence and order of accuracy.
- *numerical*: stress and multi-backend cases without a clean closed
  form (PETSc-backed Boussinesq overflow, headwater cases).
- *calibration twin*: inverse chain on synthetic truth, optimizer
  orchestration, recovery metrics. An observation point is located on the polygons of the mesh,
  on the route of the truth as on the route of the trial, so a point on a cell edge reads the
  same cell on both.
- *solver_sanity*: external solver against analytical references; may
  deliberately *not* validate the HydroModPy launcher.

Reading a failure
-----------------

The family that failed tells you where to look:

- ``unit``: one local contract or narrow behavior changed.
- ``integration``: two or more layers no longer compose.
- ``e2e``: one user-visible scenario broke across several steps.
- ``regression``: one known workflow drifted from its committed
  signature.
- ``validation`` (analytical): one numerical result no longer matches
  a trusted reference within tolerance.
- ``validation`` (MMS): the discrete scheme stopped converging at the
  expected order.
- ``validation`` (calibration twin): the inverse chain no longer
  recovers controlled truth.
- ``characterization``: a run no longer leaves on disk what a reader expects,
  or a strict ``xfail`` started to pass, which means a claim of the code is now
  honored and the marker must go.
- ``ports``: an implementation of a port no longer behaves like the others.
- ``refusals``: an input is no longer refused, or its sentence no longer
  says what to write instead.
- ``solver_sanity``: the external solver or its bundled binary
  drifted, not the orchestration.

What to run when
----------------

- During a local refactor: ``unit`` first.
- When several layers changed together: ``integration``.
- When a port, a backend or a refusal sentence changed: ``ports`` or
  ``refusals``.
- Before merging workflow-facing changes: ``regression --fast``.
- Before broader release or benchmark-sensitive changes: add
  ``regression --extensive``.
- Before solver, tolerance, or physics-sensitive changes: the
  relevant ``validation`` subset.
- Before changing one benchmark or one tolerance rationale:
  ``python -m validation_cases.run_cases ...`` for figure-first
  diagnosis.

.. _tests-validation-split:

``tests/validation/`` vs ``validation_cases/``
----------------------------------------------

HydroModPy keeps reusable scientific benchmark logic separate from the
pytest files that assert acceptance thresholds.

- ``validation_cases/`` owns benchmark definition, references,
  metadata (``metadata.toml``, ``tolerances.toml``), shared runtime
  helpers under ``validation_cases/shared/``, and direct
  ``run_case.py`` entry points for figure-first diagnosis.
- ``tests/validation/`` owns thin pytest entry points, marker
  selection (``validation``, ``steady``, ``transient``, ``petsc``),
  environment-specific skipping, and explicit assertions on scalar
  metrics returned by the case logic.

The same case can therefore run in two modes: as an automated pytest
benchmark, or as a manual diagnostic with figures and printed metrics
when tolerances need rethinking.

Edit decision matrix:

.. list-table::
   :header-rows: 1
   :widths: 38 62

   * - Editing
     - Where to edit
   * - Analytical reference, deterministic setup, new metric or
       plotting helper
     - ``validation_cases/``
   * - New marker, runtime gating, thinner assertion surface, CI
       selection
     - ``tests/validation/``
   * - A genuinely new benchmark, contract change requiring a new
       asserted metric
     - both

Local READMEs (``validation_cases/README.md`` and
``tests/validation/README.md``) carry the case-by-case maintainer
contract; this page stays the high-level map.

Tolerances and coverage expectations
-------------------------------------

Numerical tolerances live in exactly one place, never inline-duplicated:

- ``tests/TOLERANCES.md`` is the human rationale for every scientific
  tolerance. The single documented scalars are consumed in
  ``validation/`` and ``regression/`` through
  ``tests/_helpers/tolerances.py::tol('<slug>')`` so the number exists in
  one place. ``tests/unit/architecture/test_surfaces.py`` guards this:
  every ``tol()`` call must resolve to a real row, and every documented
  scalar that is used inline must be referenced through ``tol()``.
- Per-case envelopes stay in ``validation_cases/**/tolerances*.toml`` and
  are consumed at runtime via ``comparison.tolerances`` (for example
  ``profile_tol['rmse']``). These are case-owned and are *not* duplicated
  into ``TOLERANCES.md`` consumption.
- Machine-epsilon and purely structural tolerances in ``unit/`` (for
  example ``atol=1e-12`` on an exact linear solve) may stay inline with a
  one-line rationale comment; do not force them through the table.

Coverage is gated per sub-package. The job ``Coverage / floors per
sub-package`` of ``.github/workflows/main-ci.yml`` combines the data of the
``unit`` and ``scenarios`` jobs and runs ``python tools/ci/coverage_floors.py
check tools/ci/coverage_floors.toml``. The table holds one floor for each
sub-package of ``hydromodpy/`` and one for the modules at the top of each
package. A floor only goes up, through ``coverage_floors.py measure --write``,
and goes down only when files enter or leave its sub-package, with the reason
on its line. Codecov still receives the report on a push and posts its own
status (``codecov.yml``) beside the job, as an indication. ``fail_under = 80``
in ``pyproject.toml`` is a local hint, since the pytest steps of the CI pass
``--cov-fail-under=0``.

- New tests should raise coverage by asserting real behavior or a
  physical/mathematical invariant. Never add a test purely to move the
  number.

See also
--------

- :doc:`../architecture/generated/tests` for how many tests each family
  collects and which areas dominate the suite.
- :doc:`../architecture/how-to/add-a-test` for the tier, the marker and the
  fixtures of a new test.
- ``tests/README.md`` for the layout of the tree and the environment variables.

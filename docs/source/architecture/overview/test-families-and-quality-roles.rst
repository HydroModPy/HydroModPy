Test Families and Quality Roles
===============================

HydroModPy splits tests into several families because they answer
different questions. This page is the authoritative inventory of those
families, the routine commands, and the right family to consult when a
failure has to be interpreted.

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
     - ``hmp test unit``
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
     - ``hmp test regression --fast``
   * - ``regression`` (extensive)
     - Same, with heavier fixtures.
     - Wider workflow coverage; pre-merge / pre-release.
     - ``hmp test regression --extensive``
   * - ``validation`` (analytical)
     - Does the numerical result match a trusted reference?
     - Closed-form, semi-analytical, or stress benchmarks.
     - ``hmp test validation --fast`` / ``--steady`` / ``--transient``
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

- ``hmp test`` currently wraps the unit, regression, and validation
  suites.
- ``pytest`` remains the direct entry point for the integration, e2e,
  MMS, and marker-based subsets.
- The PETSc subset is Linux-only. On Windows, run it through WSL via
  ``install/enter_wsl_dev.sh``.

What each family covers
-----------------------

Unit tests (``tests/unit/``) protect Pydantic schemas, helpers,
adapters, planners, and small runtime contracts. They do not exercise
launcher behavior or persisted outputs.

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
  orchestration, recovery metrics.
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
- ``solver_sanity``: the external solver or its bundled binary
  drifted, not the orchestration.

What to run when
----------------

- During a local refactor: ``unit`` first.
- When several layers changed together: ``integration``.
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

Related pages
-------------

- :doc:`test-inventory` for a compact snapshot of how many tests are
  collected in each family and which subsystems dominate the suite.
- :doc:`code-reading-guide` for the package responsibilities behind
  the test layout.
- :doc:`../../contribute` for the contributor-facing test commands
  (lighter version of the ladder above).

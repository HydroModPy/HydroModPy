Test Families & Quality Roles
=============================

HydroModPy does not use one generic idea of "tests".

It uses several test families because they answer different questions:

- is one local behavior implemented correctly?
- do several HydroModPy subsystems still cooperate correctly?
- did one workflow output drift unexpectedly?
- does one solver-backed result remain scientifically defensible?
- does the inverse-calibration chain recover a controlled synthetic truth?

Common commands
---------------

Use these commands as the routine entry points for the main quality levels:

.. code-block:: bash

   hmp test unit
   pytest tests/integration -q
   pytest tests/e2e -q
   hmp test regression --fast
   hmp test regression --extensive
   hmp test validation --fast
   hmp test validation --steady
   hmp test validation --transient
   pytest -m solver_sanity -q
   pytest -m petsc -q
   python -m validation_cases.run_cases --solver modflownwt --regime both --no-show

Two practical notes:

- ``hmp test`` currently wraps the unit, regression, and validation suites.
- ``pytest`` remains the direct entry point for the current integration and
  end-to-end suites.

At A Glance
-----------

The top-level quality ladder is:

.. list-table::
   :header-rows: 1
   :widths: 18 32 28 22

   * - Family
     - Main question
     - Typical scope
     - Main entry point
   * - ``unit``
     - Does one local function, class, or schema behave correctly?
     - Isolated Python logic, local contracts, small fixtures
     - ``hmp test unit``
   * - ``integration``
     - Do several HydroModPy subsystems still cooperate correctly?
     - Cross-module workflows without golden files
     - ``pytest tests/integration -q``
   * - ``e2e``
     - Can one user-facing scenario complete from start to finish?
     - CLI or workspace lifecycle, export/import, resume cycles
     - ``pytest tests/e2e -q``
   * - ``regression``
     - Did a known workflow output change unexpectedly?
     - Full workflows compared to committed golden signatures
     - ``hmp test regression --fast`` or ``--extensive``
   * - ``validation``
     - Does the numerical result remain consistent with a trusted reference?
     - Analytical benchmarks, MMS, numerical stress cases, calibration twins
     - ``hmp test validation ...`` or marker-based ``pytest``
   * - ``validation_cases``
     - Can one benchmark be run outside pytest for diagnosis and figures?
     - Reusable benchmark runners and report refresh commands
     - ``python -m validation_cases.run_cases ...``

The central design choice is that HydroModPy separates:

- software correctness,
- workflow stability,
- numerical consistency,
- scientific validity.

That separation is one of the reasons the repository contains both
``tests/`` and ``validation_cases/``.

Unit Tests
----------

Location:

- ``tests/unit/``

Main role:

- verify one local behavior at a time,
- protect config schemas, helpers, adapters, planners, and small runtime
  contracts,
- fail early when a refactor breaks a narrow API or invariant.

What unit tests validate well:

- Pydantic or config validation rules,
- pure-Python numerical helpers,
- object construction and conversion contracts,
- local behavior of one class or one helper module,
- lightweight calibration or solver adapters in isolation.

What unit tests do not validate:

- full launcher behavior,
- persisted workflow outputs,
- scientific agreement with analytical references,
- external solver binaries as integrated runtimes.

Typical command:

.. code-block:: bash

   hmp test unit

Integration Tests
-----------------

Location:

- ``tests/integration/``

Main role:

- verify that several HydroModPy subsystems still work together,
- exercise realistic but still controlled workflows without relying on golden
  reference datasets,
- catch boundary mistakes between configuration, orchestration, catalog, and
  post-run layers.

What integration tests validate well:

- workspace setup and shared fixtures,
- cross-module public API workflows,
- CLI subcommands and result adapters,
- interactions between planning, runtime, and storage layers.

What integration tests do not validate:

- long-term output stability against a committed reference,
- scientific correctness of numerical results against analytical physics.

Typical command:

.. code-block:: bash

   pytest tests/integration -q

End-To-End Tests
----------------

Location:

- ``tests/e2e/``

Main role:

- verify one full user-visible scenario from start to finish,
- ensure that the platform still behaves coherently when several steps are
  chained exactly as a user would chain them.

What end-to-end tests validate well:

- project creation and roundtrip operations,
- export/import cycles,
- full simulation or calibration cycles,
- restart and resume behavior after interruption.

What end-to-end tests do not validate:

- the full scientific benchmark inventory,
- per-field numerical stability against committed signatures.

Typical command:

.. code-block:: bash

   pytest tests/e2e -q

Regression Tests
----------------

Location:

- ``tests/regression/fast/``
- ``tests/regression/extensive/``
- golden references under
  ``tests/regression/reference/golden_references/``

Main role:

- detect unexpected output drift in known HydroModPy workflows,
- compare current outputs to committed golden signatures,
- keep full-pipeline behavior stable across refactors.

HydroModPy deliberately splits regression into two tiers.

``fast`` regression
^^^^^^^^^^^^^^^^^^^

Role:

- routine non-regression coverage,
- quick enough for frequent use during development.

Typical command:

.. code-block:: bash

   hmp test regression --fast

``extensive`` regression
^^^^^^^^^^^^^^^^^^^^^^^^

Role:

- deeper end-to-end checks with heavier fixtures or wider workflow coverage,
- less suitable for rapid iteration, more suitable before larger merges or
  releases.

Typical command:

.. code-block:: bash

   hmp test regression --extensive

What regression tests validate well:

- that a known launcher or pipeline still produces the same kind of result,
- that committed signatures have not drifted unexpectedly,
- that a workflow contract remains stable over time.

What regression tests do not validate:

- whether the workflow is scientifically correct in an absolute sense,
- whether one new output drift is physically better than the old one.

A regression failure means:
"the workflow changed".

It does not automatically mean:
"the workflow became wrong".

Scientific Validation Tests
---------------------------

Location:

- ``tests/validation/``
- reusable case logic under ``validation_cases/``

Main role:

- compare solver-backed or calibration-backed results to a trusted reference,
- document explicit tolerances and benchmark intent,
- separate scientific benchmark logic from thin pytest entrypoints.

This family is itself split into several subfamilies because HydroModPy
validates more than one kind of scientific claim.

Analytical Validation
^^^^^^^^^^^^^^^^^^^^^

Location:

- ``tests/validation/analytical/``
- ``validation_cases/analytical/``

Main role:

- compare numerical results to analytical or semi-analytical references,
- validate boundary conditions, recharge forcing, recession behavior,
  heterogeneity handling, radial symmetry, and solver-family parity where the
  benchmark remains defensible.

What analytical validation proves:

- the modeled response stays within explicit tolerances relative to a trusted
  reference,
- a change did not silently degrade the physical meaning of one benchmark.

Typical commands:

.. code-block:: bash

   hmp test validation --fast
   hmp test validation --steady
   hmp test validation --transient

Manufactured Solution Tests
^^^^^^^^^^^^^^^^^^^^^^^^^^^

Location:

- ``tests/validation/mms/``

Main role:

- verify discrete convergence and expected order of accuracy,
- test the numerical method through a manufactured exact solution rather than
  through a workflow-specific physical case.

What MMS validates especially well:

- consistency of the discrete operator,
- whether refinement reduces error with the expected slope,
- whether a scheme behaves like the theory predicts before any large workflow
  orchestration is involved.

Typical command:

.. code-block:: bash

   pytest tests/validation/mms -q

Numerical Exploratory Validation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Location:

- ``tests/validation/numerical/``
- ``validation_cases/numerical/``

Main role:

- exercise stress cases, robustness cases, or multi-backend comparisons where
  no clean closed-form analytical target exists,
- keep visibility on important solver behavior that would otherwise be left to
  ad hoc manual experiments.

Typical examples in the current repository include PETSc-backed Boussinesq
overflow and headwater cases.

Typical commands:

.. code-block:: bash

   pytest tests/validation/numerical -q
   pytest -m petsc -q

The PETSc subset is Linux-only. On a Windows development machine, run it
through the WSL helper instead of trying to install PETSc in the Windows
documentation environment:

.. code-block:: powershell

   wsl.exe bash -lc "cd /mnt/c/codes/HydroModPy && bash install/enter_wsl_dev.sh --headless -- bash tools/ci/run_boussinesq_petsc_smoke.sh"

Calibration Twin Validation
^^^^^^^^^^^^^^^^^^^^^^^^^^^

Location:

- ``tests/validation/calibration/``
- ``validation_cases/calibration/``

Main role:

- validate the inverse chain rather than only the forward chain,
- verify that a calibration workflow can recover a known synthetic truth under
  controlled conditions,
- compare calibration methods on the same inverse benchmark.

What calibration twins validate well:

- parameter materialization and bounds handling,
- observation extraction,
- objective computation,
- optimizer orchestration,
- timing and recovery metrics,
- robustness to noisy, weakly constrained, or perturbed synthetic truths.

What calibration twins do not prove:

- that a method will recover truth on field data,
- that real-world identifiability issues have been solved.

Typical command:

.. code-block:: bash

   pytest tests/validation/calibration -q

Solver Sanity Validation
^^^^^^^^^^^^^^^^^^^^^^^^

Location:

- selected tests under ``tests/validation/analytical/``
- marked with ``@pytest.mark.solver_sanity``

Main role:

- validate the external solver directly against an analytical reference,
- protect against solver-level or bundled-binary drift even when the full
  HydroModPy launcher is not the right harness for the benchmark geometry.

This is an important distinction.

A ``solver_sanity`` test may validate:

- MODFLOW 6 against Theis, Hantush, or Ogata-Banks,
- a flopy-built direct model against a closed-form solution.

It may deliberately *not* validate:

- the HydroModPy pipeline itself,
- the full user-facing TOML-to-results path.

Typical command:

.. code-block:: bash

   pytest -m solver_sanity -q

Reusable Benchmark Runners
--------------------------

Location:

- ``validation_cases/``

Main role:

- keep scientific benchmark logic reusable outside pytest,
- generate figures and readable reports before changing tolerances,
- support manual diagnosis when one validation failure needs more than a red
  assertion message.

This tree is not just "tests outside tests".

It is the reusable benchmark inventory used by the pytest-facing validation
suite.

Typical commands:

.. code-block:: bash

   python -m validation_cases.run_cases --solver modflownwt --regime both --no-show
   python -m validation_cases.run_cases --solver modflow6 --regime steady --show
   python -m validation_cases.update_reports --no-show

How To Read One Failure
-----------------------

Not all failures should be interpreted the same way.

- A ``unit`` failure usually means one local contract or narrow behavior
  changed.
- An ``integration`` failure usually means two or more HydroModPy layers no
  longer compose correctly.
- An ``e2e`` failure usually means one user-visible scenario broke across
  several steps.
- A ``regression`` failure usually means one known workflow drifted away from
  its committed signature.
- An ``analytical validation`` failure usually means one numerical result no
  longer matches a trusted physical reference within tolerance.
- An ``MMS`` failure usually means the discrete method no longer converges as
  expected.
- A ``calibration twin`` failure usually means the inverse chain no longer
  recovers a controlled truth reliably enough.
- A ``solver_sanity`` failure may point to the external solver or direct SDK
  setup rather than to the HydroModPy orchestration layer.

The point of the family split is therefore not only execution convenience.

It is also interpretability.

What To Run When
----------------

Use this rule of thumb:

- before or during a local refactor: run ``unit`` first,
- when several HydroModPy layers changed together: run ``integration``,
- before merging workflow-facing changes: run ``regression --fast``,
- before broader release or benchmark-sensitive changes: add
  ``regression --extensive``,
- before accepting solver, tolerance, or physics-sensitive changes: run the
  relevant ``validation`` subset,
- before modifying one benchmark or one tolerance rationale: run the matching
  ``validation_cases/.../run_case.py`` or ``validation_cases.run_cases``
  command for a figure-first diagnosis.

Related Pages
-------------

- :doc:`tests-and-validation` explains the architectural split between
  reusable benchmark logic and pytest-facing assertions.
- :doc:`code-reading-guide` maps the main package responsibilities.
- :doc:`../../contribute` summarizes contributor-facing test and documentation
  commands.

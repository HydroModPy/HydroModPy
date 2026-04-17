Tests And Validation Boundaries
===============================

Scope
-----

HydroModPy deliberately separates reusable scientific benchmark logic from the
pytest files that assert acceptance thresholds.

Code map
--------

- ``validation_cases/``:
  reusable benchmark inventory, shared runtime helpers, references, and manual
  runners.
- ``validation_cases/shared/``:
  common execution helpers reused across several validation families.
- ``tests/validation/``:
  pytest-facing orchestration, markers, executable checks, and final
  assertions.
- local READMEs under both trees:
  repository-facing contract for maintainers.

Recommended reading path
------------------------

1. ``validation_cases/README.md``
2. ``tests/validation/README.md``
3. one case under ``validation_cases/...`` with its ``comparison.py`` and
   ``run_case.py``
4. the matching pytest entrypoint under ``tests/validation/...``

At a high level:

- ``validation_cases/`` owns benchmark definition, references, metadata, shared
  runtime helpers, and direct ``run_case.py`` entrypoints.
- ``tests/validation/`` owns pytest orchestration, test markers, executable
  checks, and the final assertions that decide whether CI passes.

This split exists so one validation case can be used in two modes:

- as an automated pytest benchmark,
- as a manual diagnostic run when a developer needs figures and printed metrics
  before changing tolerances or debugging one solver path.

Why Two Trees Exist
-------------------

``validation_cases/`` is not a test folder in disguise. It is the reusable
benchmark inventory.

Typical responsibilities in ``validation_cases/`` are:

- analytical references and literature-facing assumptions,
- deterministic launcher or runtime configuration for one benchmark,
- case metadata in ``metadata.toml`` and accepted thresholds in
  ``tolerances.toml``,
- reusable comparison functions consumed by pytest,
- manual runners and plotting helpers used outside pytest,
- shared runtime helpers under ``validation_cases/shared/``.

Typical responsibilities in ``tests/validation/`` are:

- thin pytest entrypoints,
- marker selection such as ``validation``, ``steady``, ``transient``, or
  ``petsc``,
- environment-specific skipping or executable checks,
- small, explicit assertions on scalar metrics returned by the case logic.

In short:

- put benchmark physics in ``validation_cases/``,
- put test policy in ``tests/validation/``.

Execution Paths
---------------

One launcher-backed validation case usually follows this lifecycle:

1. pytest imports one comparison function from ``validation_cases/.../comparison.py``,
2. the shared runtime executes the deterministic configuration,
3. outputs are loaded from the generated workspace,
4. the analytical or trusted reference is evaluated,
5. scalar metrics are returned,
6. ``tests/validation/...`` asserts those metrics against explicit thresholds.

The exact same case can also be launched directly through ``run_case.py`` when
one failing pytest needs a more readable figure-first diagnosis.

What To Edit Depending On The Problem
-------------------------------------

Edit ``validation_cases/`` when:

- the analytical reference is wrong or incomplete,
- the deterministic benchmark setup must change,
- a new metric or plotting helper is needed,
- a case should become manually runnable outside pytest.

Edit ``tests/validation/`` when:

- a new pytest marker or selection policy is needed,
- the suite should skip or gate on one runtime dependency,
- the assertion surface should become thinner or clearer,
- CI selection should change without rewriting the benchmark itself.

Edit both when:

- a genuinely new validation benchmark is added,
- a benchmark contract changes and pytest must assert a new metric,
- one case moves between solver families or runtime environments.

Relationship With Other Test Families
-------------------------------------

HydroModPy uses several test layers with different intents:

- unit tests check one local behavior or helper,
- regression tests guard workflow stability,
- validation tests compare numerical results to a trusted physical or
  analytical target.

Validation tests therefore tolerate internal implementation changes as long as
the benchmark remains scientifically consistent within explicit tolerances.

Current Repository Contract
---------------------------

The current repository documentation already encodes this split in two local
READMEs:

- ``validation_cases/README.md`` documents the reusable benchmark inventory,
  shared runtime files, and case-directory contract,
- ``tests/validation/README.md`` documents the pytest-facing execution model,
  markers, smoke subsets, and debugging workflow.

This overview page should stay short and architectural. Case-by-case scientific
content should remain in ``validation_cases/README.md`` and the generated
validation gallery.

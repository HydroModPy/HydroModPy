Add a Test
==========

HydroModPy ships a five-tier test tree under ``tests/``: ``unit``,
``integration``, ``e2e``, ``regression``, and ``validation``. This
page tells you which tier to pick, which marker to use, and what
fixture to reach for.

For the full role-by-role inventory and how to interpret a failure,
see :doc:`../overview/test-families-and-quality-roles`.

Pick the tier
-------------

.. list-table::
   :header-rows: 1
   :widths: 18 28 54

   * - Tier
     - When to pick it
     - Hard limits
   * - ``unit``
     - One local function, class, or schema in isolation.
     - Pure Python, no real I/O, <= 2 s per test, full tier <= 1 min.
   * - ``integration``
     - Several layers compose without a golden file.
     - Allowed to write to ``tmp_path``; <= 10 s per test.
   * - ``e2e``
     - One full user scenario through ``hmp run`` / ``hmp export`` /
       ``hmp add``.
     - Mid-size case; reads back persisted artefacts.
   * - ``regression``
     - Detect drift in a known workflow output.
     - Two flavours: ``fast`` (<= 5 min total) and ``extensive``
       (<= 30 min).
   * - ``validation``
     - Compare the numerical result to a trusted reference
       (analytical, MMS, calibration twin, solver sanity).
     - Tolerances live in ``tolerances.toml`` next to the case.

Markers in ``pytest.ini``
-------------------------

Available markers:

``regression``, ``validation``, ``analytical``, ``steady``,
``transient``, ``fast``, ``slow``, ``extensive``, ``nwt``, ``mf6``,
``petsc``, ``boussinesq``, ``intercomparison``, ``integration``,
``e2e``, ``unit``, ``coverage``, ``performance``, ``solver_sanity``,
``network``, ``binary``, ``gpu``, ``allow_subprocess``, ``timeout``,
``xdist_group``.

Add the marker on the function:

.. code-block:: python

   import pytest


   @pytest.mark.regression
   @pytest.mark.mf6
   @pytest.mark.fast
   def test_my_workflow(tmp_path):
       ...

The CLI selects subsets:

.. code-block:: bash

   hmp test unit
   hmp test regression --fast --mf6
   hmp test regression --extensive
   hmp test validation --analytical --steady
   pytest -m solver_sanity -q
   pytest -m petsc -q

``hmp test`` wraps only the ``unit``, ``regression``, and ``validation``
tiers. Run the ``integration``, ``e2e``, and MMS suites with raw
``pytest`` (for example ``pytest tests/integration/`` or
``pytest tests/e2e/``).

Where to put the file
---------------------

Mirror the package under test:

.. code-block:: text

   tests/unit/<package>/<module>/test_<feature>.py
   tests/integration/<scenario>/test_*.py
   tests/regression/fast/test_launcher_*.py
   tests/regression/extensive/test_launcher_*.py
   tests/validation/analytical/<case>/test_*.py
   tests/validation/numerical/<case>/test_*.py
   tests/validation/mms/<case>/test_*.py
   tests/validation/calibration/<case>/test_*.py

Reusable fixtures
-----------------

Top-level ``conftest.py`` exposes:

- ``tmp_workspace`` -- a fresh workspace directory (a ``Path`` rooted in
  ``tmp_path`` with the standard ``data/`` / ``projects/`` layout).
- ``minimal_config`` -- a ready-to-run ``HydroModPyConfig`` for the
  smallest case (extend via ``model_copy(update=...)``).

For a DuckDB/Zarr catalog seeded on ``tmp_path``, use the
``tests._helpers.fixtures_catalog.simulation_catalog`` context manager.

Use them to avoid re-implementing scaffolding in every test.

Unit-test pattern
-----------------

.. code-block:: python

   # tests/unit/data/test_load_result.py
   from hydromodpy.data.contracts.load_result import LoadResult


   def test_load_result_concat(tmp_path):
       a = LoadResult(points=[...], fields=[], warnings=[])
       b = LoadResult(points=[...], fields=[], warnings=["warn"])
       merged = a.merge(b)
       assert len(merged.points) == 2
       assert merged.warnings == ["warn"]

Integration pattern
-------------------

.. code-block:: python

   # tests/integration/test_overview_workflow.py
   import pytest

   import hydromodpy as hmp


   @pytest.mark.integration
   def test_overview(tmp_workspace, minimal_overview_toml):
       hmp.run(minimal_overview_toml)  # [workflow] mode = "overview"
       assert (tmp_workspace / "data").exists()

Regression pattern
------------------

.. code-block:: python

   # tests/regression/fast/test_simulation_regression_fast_mf6.py
   import pytest

   from tests.regression.golden_utils import (
       load_golden_reference,
       resolve_tiered_golden_file,
       snapshot_signature,
       write_golden_reference,
   )


   @pytest.mark.regression
   @pytest.mark.mf6
   @pytest.mark.fast
   def test_simulation_regression_fast_mf6(tmp_path, update_goldens):
       signature = snapshot_signature(run_workflow(tmp_path, ...))
       golden = resolve_tiered_golden_file(
           test_file=__file__, filename="simulation_regression_fast_mf6.json"
       )
       if update_goldens:
           write_golden_reference(golden, signature)
       assert signature == load_golden_reference(golden)

Refresh the golden with ``pytest tests/regression/ --update-goldens``;
review the diff before committing.

Validation pattern
------------------

A validation case lives in *two* trees:

- the **benchmark logic** in
  ``validation_cases/<case>/{run_case.py, comparison.py,
  metadata.toml, tolerances.toml}``;
- the **pytest entry** in ``tests/validation/<family>/test_*.py``
  that imports the comparison function and asserts metrics.

The split exists so the same case can be run as an automated test or
launched manually for figure-first diagnosis (``python -m
validation_cases.run_cases``).

Tolerances are never inline magic numbers. A case envelope lives in the
case's ``tolerances.toml`` and is read through ``comparison.tolerances``;
a single documented scalar from ``tests/TOLERANCES.md`` is read through
``tests/_helpers/tolerances.py::tol('<slug>')``. See ``tests/TOLERANCES.md``
for the global policy and ``tests/unit/test_tolerances_single_source.py``
for the drift guard.

Solver-sanity pattern
---------------------

When the test should validate the **external solver** rather than
the HydroModPy launcher, mark it ``solver_sanity``:

.. code-block:: python

   @pytest.mark.solver_sanity
   def test_modflow6_against_theis(tmp_path):
       ...

That subset is meant to flag solver-binary drift independently of
HydroModPy's orchestration.

Pitfalls flagged by the layer matrix
------------------------------------

- The test layer must not import ``hydromodpy`` private modules with
  a leading underscore (``_api``, ``_lazy``, ``_bootstrap``).
- A unit test must not write to a network resource. Mock at the
  ``HTTPClient`` level (``core/io/http_client.py``).
- Validation tests must keep tolerances in their case-local
  ``tolerances.toml`` (case envelopes) or in ``tests/TOLERANCES.md`` via
  ``tol('<slug>')`` (documented scalars); do not hard-code numeric
  thresholds in the pytest file.

Coverage expectation
--------------------

Coverage is gated by Codecov, not by ``pyproject``: the ``patch`` target
is 80 % (your diff must be at least 80 % covered) and the ``project``
target is ``auto`` (overall coverage must not drop). ``[tool.coverage]
fail_under`` in ``pyproject.toml`` is not enforced by CI. Raise coverage
by asserting real behavior or a physical/mathematical invariant, never by
adding a test purely to hit a line.

See also
--------

- :doc:`../overview/test-families-and-quality-roles` for the full
  ladder.
- :doc:`../overview/test-inventory` for the current suite snapshot by
  family and subsystem.
- :doc:`/contribute` for the contributor workflow.
- ``tests/README.md`` and ``validation_cases/README.md`` for the
  in-repo conventions.

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
``petsc``, ``integration``, ``coverage``, ``solver_sanity``,
``intercomparison``.

Add the marker on the function:

.. code-block:: python

   import pytest


   @pytest.mark.regression
   @pytest.mark.mf6
   @pytest.mark.fast
   def test_my_workflow(catalog_with_data):
       ...

The CLI selects subsets:

.. code-block:: bash

   hmp test unit
   hmp test regression --fast --mf6
   hmp test regression --extensive
   hmp test validation --analytical --steady
   pytest -m solver_sanity -q
   pytest -m petsc -q

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

- ``tmp_workspace`` -- a fresh ``Workspace`` rooted in ``tmp_path``.
- ``minimal_config`` -- a ready-to-run ``HydroModPyConfig`` for the
  smallest case.
- ``catalog_with_data`` (under ``tests/unit/conftest.py``) -- a
  catalog seeded with a single fake simulation and its Parquet
  views.

Use them to avoid re-implementing scaffolding in every test.

Unit-test pattern
-----------------

.. code-block:: python

   # tests/unit/data/test_load_result.py
   from hydromodpy.data.contracts.results import LoadResult


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

   from hydromodpy.project import Project


   @pytest.mark.integration
   def test_overview(tmp_workspace, minimal_config):
       project = Project(minimal_config, workspace=tmp_workspace)
       project.overview()
       assert (tmp_workspace.root / "data").exists()

Regression pattern
------------------

.. code-block:: python

   # tests/regression/fast/test_launcher_simulation_fast_mf6.py
   import pytest

   from tests.support.golden import assert_golden


   @pytest.mark.regression
   @pytest.mark.mf6
   @pytest.mark.fast
   def test_launcher_simulation_fast_mf6(catalog_with_data):
       result = run_workflow(catalog_with_data, ...)
       assert_golden(result, "fixtures/launcher_simulation_fast_mf6.json")

Update the golden manually with ``hmp test regression
--update-goldens``; review the diff before committing.

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

Tolerances live in the case's ``tolerances.toml`` and never inline
in the test. See ``tests/TOLERANCES.md`` for the global policy.

Solver-sanity pattern
---------------------

When the test should validate the **external solver** rather than
the HydroModPy launcher, mark it ``solver_sanity``:

.. code-block:: python

   @pytest.mark.solver_sanity
   def test_modflow6_against_theis(...):
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
  ``tolerances.toml``; do not hard-code numeric thresholds in the
  pytest file.

See also
--------

- :doc:`../overview/test-families-and-quality-roles` for the full
  ladder.
- :doc:`/contribute` for the contributor workflow.
- ``tests/README.md`` and ``validation_cases/README.md`` for the
  in-repo conventions.

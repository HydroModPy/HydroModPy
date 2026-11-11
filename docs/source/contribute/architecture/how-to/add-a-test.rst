Add a test
==========

The test tree under ``tests/`` has one folder per family. This page tells you
which family to pick, which marker to use, which fixture to reach for, and how
to run the tests. The families themselves, and how to read a failure of each,
are in :doc:`/contribute/project/tests`.

Pick the tier
-------------

.. list-table::
   :header-rows: 1
   :widths: 18 30 52

   * - Tier
     - When to pick it
     - Limits
   * - ``unit``
     - One local function, class or schema in isolation.
     - Pure Python, no real I/O outside ``tmp_path``. Timeout 60 s.
   * - ``integration``
     - Several layers compose, without a golden file.
     - May write to ``tmp_path``. Timeout 300 s.
   * - ``e2e``
     - One full user scenario through ``hmp run``, ``hmp export`` or
       ``hmp data lock``.
     - Reads back what was persisted. Timeout 1800 s.
   * - ``regression``
     - Detect drift in a known workflow output.
     - ``fast`` (a few minutes in total) and ``extensive`` (heavier fixtures).
       Timeout 300 s.
   * - ``validation``
     - Compare a numerical result with a trusted reference (analytical, MMS,
       calibration twin, solver sanity).
     - Tolerances live next to the case. Timeout 900 s.
   * - ``characterization``
     - What one real run leaves on disk, read with the formats a stranger would
       use.
     - Five strict ``xfail`` cases record claims the code does not honor yet.
   * - ``ports``
     - Every implementation of one port behaves the same. One file per port,
       ``tests/ports/test_<port>.py``.
     - Parametrized over the names of the registry, never over a written list.
       A case that cannot run is a skip with the reason the object declares.
       Timeout 900 s.
   * - ``refusals``
     - A wrong input is refused with its class, its code and a sentence that
       says what to do. One file per family, ``tests/refusals/test_<family>.py``.
     - One row per input. A table over a closed set checks that its rows equal
       the set. Timeout 60 s.

``tests/conftest.py`` tags a test with its tier marker and a default timeout
from its folder, so you do not write ``@pytest.mark.unit``.

Markers
-------

``pytest.ini`` declares every marker with its meaning and runs with
``--strict-markers``: an undeclared marker is an error. The ones you will use
most are ``regression``, ``validation``, ``analytical``, ``steady``,
``transient``, ``fast``, ``slow``, ``extensive``, ``nwt``, ``mf6``, ``petsc``,
``boussinesq``, ``solver_sanity``, ``network``, ``binary`` and
``allow_subprocess``.

.. code-block:: python

   import pytest


   @pytest.mark.regression
   @pytest.mark.fast
   @pytest.mark.mf6
   def test_my_workflow(tmp_path): ...

In a source checkout, ``python -m tools.dev test`` selects subsets of three tiers:

.. code-block:: bash

   python -m tools.dev test unit
   python -m tools.dev test regression --fast --mf6
   python -m tools.dev test regression --extensive
   python -m tools.dev test validation --analytical --steady

The other tiers go through ``pytest`` (for example
``pytest tests/integration -q``, ``pytest -m solver_sanity -q``,
``pytest -m petsc -q``).

Where to put the file
---------------------

Mirror the package under test:

.. code-block:: text

   tests/unit/<package>/test_<feature>.py
   tests/integration/<area>/test_*.py
   tests/regression/fast/test_*.py
   tests/regression/extensive/test_*.py
   tests/validation/analytical/{steady,transient}/...
   tests/validation/numerical/{steady,transient}/...
   tests/validation/mms/test_*.py
   tests/validation/calibration/test_*.py
   tests/processes/<package>/test_*.py

A test that starts several processes goes under ``tests/processes/``, not under
``tests/unit/``. Its children start with ``spawn``, so it runs on Linux and Windows.

Reusable fixtures
-----------------

The top-level ``tests/conftest.py`` exposes:

- ``tmp_workspace``: a fresh workspace directory, rooted in ``tmp_path`` with the
  standard ``data/`` and ``projects/`` layout.
- ``minimal_config``: a ready-to-run ``HydroModPyConfig`` for the smallest case.
  Extend it with ``model_copy(update=...)``.
- ``update_goldens``: true when pytest runs with ``--update-goldens``.

For a DuckDB and Zarr catalog seeded under ``tmp_path``, use the
``tests._helpers.fixtures_catalog.simulation_catalog`` context manager.
``tests/_helpers/`` also holds the doubles to use instead of a network call, a
Whitebox run or a solver spawn.

Unit pattern
------------

``tests/unit/model/transport/test_transport_config.py`` reads one table of the
``[transport]`` section by the registry name of its solver and checks what it
holds:

.. code-block:: python

   from hydromodpy.model.transport.transport_config import TransportConfig


   def test_a_table_is_read_under_the_registry_name_of_its_solver() -> None:
       cfg = TransportConfig.model_validate({"mt3dms": {"sconc_init": 7.5, "disp_long": 12.0}})

       options = cfg.options_of("mt3dms")
       assert options.sconc_init == 7.5 and options.disp_long == 12.0

Integration pattern
-------------------

``tests/integration/test_shared_fixtures.py`` shows the shared workspace fixture
at work:

.. code-block:: python

   import hydromodpy as hmp
   from hydromodpy.results.catalog.indexer import rebuild_index
   from tests._helpers.sealed_runs import make_project


   def test_tmp_workspace_is_openable_as_a_catalog(tmp_workspace):
       project = make_project(tmp_workspace / "projects" / "demo")
       rebuild_index(project)
       with hmp.open(project).store as catalog:
           assert catalog.list_simulations().empty

Regression pattern
------------------

A regression test runs a small workflow and compares its signature with a
committed golden file. ``tests/regression/fast/test_simulation_regression_fast_mf6_regression.py``
is one line of arguments to a shared helper:

.. code-block:: python

   @pytest.mark.regression
   @pytest.mark.fast
   @pytest.mark.mf6
   def test_simulation_regression_fast_mf6_regression(update_goldens) -> None:
       run_simulation_regression(
           test_file=__file__,
           config_name="run_fast_mf6.toml",
           golden_filename="simulation_regression_fast_mf6_npy_signatures.json",
           update_goldens=update_goldens,
           ...,
       )

The helpers are in ``tests/regression/golden_utils.py``
(``snapshot_signature``, ``load_golden_reference``, ``write_golden_reference``).
Refresh a golden with ``pytest tests/regression/ --update-goldens`` and review
the diff before you commit it. A golden that moved says the workflow changed, not
that it became wrong.

Validation pattern
------------------

A validation case lives in two trees:

- the benchmark logic in ``validation_cases/<case>/`` (``run_case.py``,
  ``comparison.py``, ``metadata.toml``, ``tolerances.toml``);
- the pytest entry in ``tests/validation/<family>/test_*.py``, which imports the
  comparison function and asserts the metrics.

The split lets the same case run as an automated test or by hand, for a
figure-first diagnosis (``python -m validation_cases.run_cases``).

Tolerances are never inline magic numbers. A case envelope lives in the case's
``tolerances.toml`` and is read through ``comparison.tolerances``. A single
documented scalar from ``tests/TOLERANCES.md`` is read through
``tests/_helpers/tolerances.py::tol('<slug>')``.
``tests/unit/architecture/test_surfaces.py`` is the drift guard.

When the test should check the external solver and not the HydroModPy launcher,
mark it ``solver_sanity``. That subset flags solver-binary drift independently of
the orchestration.

.. _run-the-tests:

Run the tests
-------------

Run the folder of the area you touched, and the architecture gate. CI runs the
whole suite.

.. code-block:: bash

   python -m pytest tests/unit/model -q
   python -m pytest tests/unit/architecture -q

**Parallel runs.** ``pytest.ini`` already sets ``--dist=loadgroup``, which keeps
the tests that share an ``xdist_group`` on one worker. Keep it: ``--dist
loadscope`` ignores the groups. On a workstation use ``-n 8`` or fewer, never
more workers than cores.

.. code-block:: bash

   python -m pytest tests/unit -q -n 8 --dist loadgroup

CI uses ``-n 2``.

**Whitebox tests run in series.** The native Whitebox binding dies, and takes
the pytest worker with it, when several DEM workflows run in one long-lived
process. ``tests/conftest.py`` puts the Whitebox-backed tests in one xdist group,
and the CI steps that run a tier in parallel exclude them and run them in a
serial step. Do the same when you run a tier locally: run the Whitebox files
without ``-n``. ``tests/unit/architecture/test_surfaces.py``
checks the workflows. Never run two pytest sessions on the same scratch root.

**Scratch folder.** Tests write to ``HMP_TEST_SCRATCH_ROOT``, ``/tmp/hydromodpy_tests/``
by default. When ``/tmp`` is a small memory-backed filesystem, or shared with other
sessions, a full disk truncates raster files and the failure looks like a bug in
your change. Point the variable at a disk before you suspect your diff:

.. code-block:: bash

   export HMP_TEST_SCRATCH_ROOT=$HOME/.cache/hmp-test-scratch

Pitfalls
--------

- A unit test must not reach the network. Mock at the ``HTTPClient`` level
  (``core/io/http_client.py``) or use a double from ``tests/_helpers/``.
- A validation test keeps its tolerances in the case ``tolerances.toml`` or in
  ``tests/TOLERANCES.md`` through ``tol('<slug>')``. It does not hard-code a
  threshold.
- Raise coverage by asserting a real behavior or an invariant, never by adding a
  test to hit a line. Codecov gates the patch at 80 % and the project at ``auto``;
  ``fail_under`` in ``pyproject.toml`` is not a CI gate.

See also
--------

- :doc:`/contribute/project/tests` for the families and how to read a failure.
- :doc:`/contribute/architecture/generated/tests` for the inventory of the suite.
- ``tests/README.md`` and ``validation_cases/README.md`` for the conventions kept
  in the tree.

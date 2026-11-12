Add a test
==========

The test tree under ``tests/`` has one folder per family. This page says which family to
pick, which marker and fixture to use, and how to run the tests. The families and how to
read a failure of each are in :doc:`/contribute/project/tests`. The inventory of the suite is
generated in :doc:`../generated/tests`.

Pick the family
---------------

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Folder
     - When to pick it
   * - ``unit``
     - One kernel, function, class or schema in isolation, with one file per module. Pure
       Python, no real I/O outside ``tmp_path``. Sign, unit and sentinel tests go here.
   * - ``scenarios``
     - A small synthetic project played once by the real pipeline, then read back.
   * - ``refusals``
     - A wrong input is refused with its class, its code and a sentence that says what to do.
       One file per family, ``tests/refusals/test_<family>.py``, with one row per input.
       A table over a closed set checks that its rows equal the set.
   * - ``ports``
     - Every implementation of one port behaves the same. One file per port,
       ``tests/ports/test_<port>.py``, parametrized over the names of the registry and never
       over a written list. A case that cannot run is a skip with the reason the object
       declares.
   * - ``unit/architecture``
     - A structural contract of the code. See :doc:`fix-an-architecture-gate`.
   * - ``regression``
     - Drift in a known workflow output, against a committed golden file. ``fast`` runs in a
       few minutes, ``extensive`` uses heavier fixtures.
   * - ``validation``
     - A numerical result against a trusted reference (analytical, MMS, calibration twin,
       solver sanity). The tolerances live next to the case.
   * - ``integration``, ``e2e``
     - Several layers composed, or one user scenario through ``hmp run``, ``hmp export`` or
       ``hmp data lock``. Older folders. They fold into the families above as packages move.
   * - ``processes``
     - A test that starts several processes on one folder. Its children start with ``spawn``,
       so it runs on Linux and Windows.

``tests/conftest.py`` tags a test with the marker of its folder and a default timeout, so you
do not write ``@pytest.mark.unit``. Mirror the package under test, as in
``tests/unit/<package>/test_<feature>.py``.

Markers
-------

``pytest.ini`` declares every marker with its meaning and runs with ``--strict-markers``, so
an undeclared marker is an error. A regression test carries ``regression``, ``fast`` or
``extensive``, and the solver it needs (``mf6``, ``nwt``, ``petsc``). A validation test
carries ``validation`` and ``analytical`` or another subset. A test that spawns a process
needs ``allow_subprocess``.

In a source checkout, ``python -m tools.dev test`` selects subsets of three tiers.

.. code-block:: bash

   python -m tools.dev test unit
   python -m tools.dev test regression --fast --mf6
   python -m tools.dev test validation --analytical --steady

Reusable fixtures
-----------------

The top-level ``tests/conftest.py`` exposes ``tmp_workspace`` (a fresh workspace rooted in
``tmp_path`` with the standard ``data/`` and ``projects/`` layout), ``minimal_config`` (a
ready-to-run ``HydroModPyConfig``, extended with ``model_copy(update=...)``) and
``update_goldens`` (true under ``--update-goldens``).

For a DuckDB and Zarr catalog seeded under ``tmp_path``, use the context manager
``simulation_catalog`` of ``tests/_helpers/fixtures_catalog.py``. ``tests/_helpers/`` also
holds the doubles to use instead of a network call, a Whitebox run or a solver spawn.

Unit pattern
------------

This test reads one table of the ``[transport]`` section by the registry name of its solver.

.. literalinclude:: /../../tests/unit/model/transport/test_transport_config.py
   :pyobject: test_table_is_read_under_its_solver_name

Integration pattern
-------------------

This test shows the shared workspace fixture at work.

.. literalinclude:: /../../tests/integration/test_shared_fixtures.py
   :pyobject: test_tmp_workspace_is_openable_as_a_catalog

Regression pattern
------------------

A regression test runs a small workflow and compares its signature with a committed golden
file. The test is one call to a shared helper.

.. literalinclude:: /../../tests/regression/fast/test_simulation_regression_fast_mf6_regression.py
   :pyobject: test_simulation_regression_fast_mf6_regression

The helpers are in ``tests/regression/golden_utils.py``. Refresh a golden with
``pytest tests/regression/ --update-goldens`` and review the diff before you commit it. A
golden that moved says the workflow changed, and it may still be right. Never edit
``tests/regression/frozen_runs/`` nor ``tests/regression/frozen_replay/v2.0.0/``.

Validation pattern
------------------

A validation case lives in two trees. The benchmark logic is in ``validation_cases/<case>/``
(``run_case.py``, ``comparison.py``, ``metadata.toml``, ``tolerances.toml``). The pytest entry
is in ``tests/validation/<family>/test_*.py``, which imports the comparison function and
asserts the metrics. The split lets the same case run as a test or by hand, for a figure-first
diagnosis with ``python -m validation_cases.run_cases``.

A tolerance is never an inline number. A case envelope lives in the ``tolerances.toml`` of the
case. A single documented scalar of ``tests/TOLERANCES.md`` is read with
``tol('<slug>')`` from ``tests/_helpers/tolerances.py``. ``tests/unit/architecture/test_surfaces.py``
guards the table. A test that must check the external solver and not the launcher is marked
``solver_sanity``, so solver-binary drift shows apart from the orchestration.

.. _run-the-tests:

Run the tests
-------------

Run the folder of the area you touched, and the architecture gate. CI runs the whole suite.

.. code-block:: bash

   python -m pytest tests/unit/model -q
   python -m pytest tests/unit/architecture -q

**Parallel runs.** ``pytest.ini`` sets ``--dist=loadgroup``, which keeps the tests of one
``xdist_group`` on one worker. Keep it, because ``loadscope`` ignores the groups. On a
workstation use ``-n 8`` or fewer, never more workers than cores. CI uses ``-n 2``.

**Whitebox tests run in series.** The native Whitebox binding dies, and takes the pytest
worker with it, when several DEM workflows run in one long-lived process. ``tests/conftest.py``
puts the Whitebox-backed tests in one xdist group, and the CI steps that run a tier in parallel
exclude them and run them in a serial step. Do the same locally, and never run two pytest
sessions on the same scratch root.

**Scratch folder.** Tests write to ``HMP_TEST_SCRATCH_ROOT``, ``/tmp/hydromodpy_tests/`` by
default. When ``/tmp`` is small, memory-backed or shared, a full disk truncates raster files and
the failure looks like a bug in your change. Point the variable at a disk first.

.. code-block:: bash

   export HMP_TEST_SCRATCH_ROOT=$HOME/.cache/hmp-test-scratch

Pitfalls
--------

- A unit test must not reach the network. Mock at the ``HTTPClient`` level
  (``hydromodpy/core/io/fetch.py``) or use a double from ``tests/_helpers/``.
- Raise coverage by asserting a real behavior or an invariant, never by adding a test to hit a
  line. Codecov gates the patch at 80 % and the project at ``auto``. ``fail_under`` in
  ``pyproject.toml`` is not a CI gate.

See also
--------

- :doc:`/contribute/project/tests` for the families and how to read a failure.
- ``tests/README.md`` and ``validation_cases/README.md`` for the conventions kept in the tree.

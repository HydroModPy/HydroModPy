Fix a failing architecture gate
===============================

``tests/unit/architecture/`` holds the structural contracts of the code. CI runs
it as the job ``Architecture / layer matrix``. It fails on a pull request when an
import, a declaration or an allowlist no longer matches the contract, and the
failure names the rule. This page says how to read it and what to do for each
kind of failure. The list of every rule, with the file that holds it, is
generated: :doc:`../generated/guards`.

Run it
------

.. code-block:: bash

   python -m pytest tests/unit/architecture -q -n 2

It takes about a minute and a half with two workers. To run one rule, name the
file.

The rule you broke is the file name of the first failure. Find it in the table
below.

What to do, by failing test
---------------------------

``test_layer_matrix.py``
   *"N layer-matrix violations: physics -> spatial 3 via from"*. An import crosses
   a layer boundary that ``layer_matrix.yaml`` does not grant. The message counts
   the edges by pair, without the lines. List them:

   .. code-block:: bash

      python - <<'PY'
      import pathlib
      from tools.audit.build_graph import scan_package
      for e in scan_package(pathlib.Path("hydromodpy")):
          if (e.src_pkg, e.tgt_pkg) == ("physics", "spatial"):
              print(f"{e.src_file}:{e.lineno} {e.kind} {e.target_module}")
      PY

   Replace the pair with the one in the message. Then fix the import. Move the
   symbol down to a layer both sides may import (often ``core``), or call it
   through a port the lower layer defines. Do not add the edge to the YAML to make
   the test pass: a new edge that violates the matrix is a regression, so propose
   it in an issue first. An import under ``TYPE_CHECKING``, inside a function, or
   written as a string in a lazy-import table counts like any other. The same file
   fails when a package has no row in the matrix, a row has no package, a
   tolerance names an unknown layer or repeats an allowed edge, or a package has no
   page in :doc:`../packages/index`.

``test_layer_matrix_page.py``
   *"docs/source/contribute/architecture/layer-matrix.partial.rst is stale"*. The
   committed fragment is generated from the YAML. Run
   ``python -m tools.doc_contracts`` and commit the result.

``test_package_layouts.py``
   A package with a ``<package>_layout.yaml`` (``data``, ``calibration``,
   ``display``) orders its parts, and a part may import only the parts in its row.
   The message names the part and the import. Either move the import, or, if the
   dependency is real, reorder the rows in the layout file and in the package
   README together. A row may name only rows above it, so a cycle cannot be
   declared. Another layer may import only the modules listed under ``public``.

``test_data_source_port_stands_alone.py`` and ``test_terrain_port_stands_alone.py``
   A port promises a third-party plugin that it needs nothing of HydroModPy beyond
   the port module and its contracts. The layer matrix cannot see this, because
   the parts sit in one layer. Remove the import: a source must not reach a
   manager, a catalog or a workspace, and a terrain engine must not import another
   part of ``spatial``.

``test_cli_boundary.py``
   Only ``hydromodpy/__main__.py`` may import ``hydromodpy.cli``. Put the logic in
   the layer it belongs to and have the command call it. The CLI stays thin.

``test_storage_boundary.py``
   A direct ``duckdb.connect`` in the public API or a user-facing command. Go
   through the catalog or cache adapter. The files allowed to open DuckDB directly are
   listed in ``ALLOWED_DIRECT_DUCKDB_FILES`` of the test, and the cases are
   described in :ref:`direct-duckdb-access`.

``test_solver_private_attributes.py``
   A private name (``obj._name``) read inside ``solver/<package>/`` must be declared
   in that same sub-package. Expose the value through a public method or field of
   the owner. The two MODFLOW backends and the shared helpers are held to it.

``test_step_payload_keys.py``
   A pipeline step declares the payload keys it reads and writes, as the class
   attributes ``reads`` and ``writes``, and they must match what its code touches,
   in both directions. Edit the two tuples of the step. A key the step no longer
   touches must go.

``test_run_context_state_surface.py``, ``test_run_product_reaches_its_consumer.py``, ``test_workflow_context_members_have_a_reader.py``
   These keep what a solver adapter receives narrow. An adapter reads the view
   ``ctx.state`` (``setup``, ``cfg`` and ``sim_id``), the model and output folder
   of its own run from ``ctx.model`` and ``ctx.output_dir``, the models it depends
   on from ``ctx.dependency_models`` and the catalog handle from ``ctx.store``. It
   does not reach into the execution registries. A member of ``WorkflowContext``
   that nothing reads is removed. A module that really needs a registry is added
   to the short allowlist of the test, which is a decision to state in the pull
   request.

``test_no_vanilla_raise.py``
   ``raise ValueError`` and ``raise RuntimeError`` are banned in the modules of its
   ``SCOPE``. Raise a typed exception from ``hydromodpy.core.exceptions``. Add a
   module to ``SCOPE`` once it is clean.

``test_tolerances_single_source.py``
   A ``tol('<slug>')`` call that matches no row of ``tests/TOLERANCES.md``, or a
   documented scalar that is written inline again. Fix the slug, or add the row to
   the table, and read the value through ``tol()``.

``test_whitebox_tests_run_serially.py``
   A CI step runs a Whitebox-backed test file in parallel. Exclude the file from
   the parallel step and keep it in the serial one. See :ref:`run-the-tests`.

``test_no_legacy_surface.py``
   A retired name appears in the docs, the examples, the package or the tests.
   Delete it.

When the contract is what is wrong
----------------------------------

Sometimes the code is right and the contract is old. The contract files are
``layer_matrix.yaml`` (rows, tolerances, exempt files) and the three
``*_layout.yaml`` files. Change them in a pull request of their own, with the
reason in the tolerance entry, because a tolerance without a rationale fails
review. Then regenerate the pages (``python -m tools.doc_contracts``) and update
the README of the package whose rows moved. Never add a tolerance silently.

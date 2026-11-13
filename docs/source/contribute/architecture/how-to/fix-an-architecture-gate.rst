Fix a failing architecture gate
===============================

``tests/unit/architecture/`` holds the structural contracts of the code. CI runs it as the
job ``Architecture / layers, surface and two threads``. It fails when an import, a
declaration or an allowlist no longer matches the contract, and the failure names the rule.
The list of every rule, with the file that holds it, is generated in
:doc:`../generated/guards`. This page says what to do for the common failures.

Run it
------

.. code-block:: bash

   python -m pytest tests/unit/architecture -q -n 2

To run one rule, name the file and select the test with ``-k``. Most rules live in
``test_layers.py`` (who reads whom), ``test_run_path.py`` (what the path of a run reads and
writes), ``test_surfaces.py`` (what is public and held) and ``test_code_rules.py`` (the
code rules that the syntax alone can check). The test name of the first failure says
which rule broke.

What to do, by failing test
---------------------------

``test_layers.py``, the layer matrix
   *"N layer-matrix violations: solver -> data 3 via from"*. An import crosses
   a layer boundary that ``layer_matrix.yaml`` does not grant. The message counts
   the edges by pair, without the lines. List them:

   .. code-block:: bash

      python - <<'PY'
      import pathlib
      from tools.audit.build_graph import scan_package
      for e in scan_package(pathlib.Path("hydromodpy")):
          if (e.src_pkg, e.tgt_pkg) == ("solver", "data"):
              print(f"{e.src_file}:{e.lineno} {e.kind} {e.target_module}")
      PY

   Replace the pair with the one in the message, then fix the import. Move the symbol down
   to a layer both sides may import, often ``core``, or call it through a port the lower
   layer defines. Never add the edge to the YAML to make the test pass, because a new edge
   that breaks the matrix is a regression and needs an issue first. An import under
   ``TYPE_CHECKING`` or inside a function counts like any other. The layers are rendered in
   :doc:`../generated/layers`.

``test_layers.py``, the generated matrix page
   The committed fragment is stale against the YAML. Run ``python -m tools.doc_contracts``
   and commit the result.

``test_package_layouts.py``
   A package with a ``<package>_layout.yaml`` orders its parts, and a part may
   import only the parts in its row. The message names the part and the import.
   Either move the import, or, if the dependency is real, reorder the rows in the
   layout file and the sentences of the package page together. A row may name
   only rows above it, so a cycle cannot be declared. Another layer may import
   only the modules listed under ``public``.

``test_layers.py``, a port that stands alone
   A port promises a third-party plugin that it needs nothing of HydroModPy beyond the port
   module and its contracts. Remove the import. A source must not reach a manager, a catalog
   or a workspace.

``test_layers.py``, the storage boundary
   A direct ``duckdb.connect`` outside the files the rule allows. Go through the catalog or
   cache adapter, as :ref:`direct-duckdb-access` says.

``test_layers.py``, private solver attributes
   A private name (``obj._name``) read inside ``solver/<package>/`` must be declared
   in that same sub-package. Expose the value through a public method or field of
   the owner. The two MODFLOW backends and the shared helpers are held to it.

``test_run_path.py``, the payload keys of a step
   A pipeline step declares the payload keys it reads and writes, as the class
   attributes ``reads`` and ``writes``, and they must match what its code touches,
   in both directions. Edit the two tuples of the step. A key the step no longer
   touches must go.

``test_run_path.py``, what a solver adapter reads
   A flow adapter reads the ``Model``, its options and its ``RunSlot``, and nothing of
   ``ctx.state`` or ``ctx.store``. A transport adapter reads the view ``ctx.state``, the runs
   in ``ctx.upstream`` and the catalog handle ``ctx.store``. A module that really needs a
   registry goes to the short allowlist of the test, a decision to state in the pull request.

``test_surfaces.py``, typed exceptions
   ``raise ValueError`` and ``raise RuntimeError`` are banned in the modules of its
   ``SCOPE``. Raise a typed exception from ``hydromodpy.core.exceptions``. Add a
   module to ``SCOPE`` once it is clean.

``test_surfaces.py``, one source for tolerances
   A ``tol('<slug>')`` call that matches no row of ``tests/TOLERANCES.md``, or a
   documented scalar that is written inline again. Fix the slug, or add the row to
   the table, and read the value through ``tol()``.

``test_surfaces.py``, Whitebox tests run serially
   A CI step runs a Whitebox-backed test file in parallel. Exclude the file from
   the parallel step and keep it in the serial one. See :ref:`run-the-tests`.

``test_surfaces.py``, no legacy surface
   A retired name appears in the docs, the examples, the package or the tests.
   Delete it.

When the contract is what is wrong
----------------------------------

Sometimes the code is right and the contract is old. The contract files are
``layer_matrix.yaml`` and the ``*_layout.yaml`` files. Change them in a pull request of their
own that says why, then run ``python -m tools.doc_contracts``. Never add an edge silently.

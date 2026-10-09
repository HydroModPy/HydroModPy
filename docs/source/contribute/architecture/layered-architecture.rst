Layered architecture
====================

HydroModPy is a layered dependency graph. Every top-level subpackage of
``hydromodpy/`` is one layer and may import only the layers that
``tests/unit/architecture/layer_matrix.yaml`` grants it. The YAML file is the
normative contract. The matrix below is generated from it by
``tools/doc_contracts.py`` at every build, so it cannot drift, and the gate reads
the same YAML. The layers drawn as a graph, with the transitive reduction of the
edges, are in :doc:`generated/layers`.

Ports and adapters at the storage edge
--------------------------------------

The V1 storage contract is DuckDB-first, not backend-agnostic in every runtime
path. The project catalog uses
:class:`~hydromodpy.results.catalog.ports.CatalogBackend`, with ``DuckDBBackend``
as the in-tree implementation. The data cache uses a separate DuckDB cache adapter.
CLI diagnostics, migration runners and portable-package snapshots may open DuckDB
directly, in the cases listed in :ref:`direct-duckdb-access`.

Field readers go through ``hmp.read``, which dispatches to the Zarr or Parquet store
through the field registry. See :doc:`/contribute/architecture/packages/results`
for the Python surface.

The rules
---------

**Held by the gate.** A pull request that breaks one of these fails
``Architecture / layer matrix``.

1. One layer per top-level subpackage, and one row per package in the matrix.
2. An import is an edge, and the edge must be in the matrix or in its list of
   tolerances, each with a reason. The scanner counts every import: at module level, inside a function, under ``TYPE_CHECKING``,
   ``import_module`` on a literal, and a dotted path written in a lazy-import
   table.
3. ``core`` is the kernel leaf. It imports no sibling layer.
4. ``hydromodpy_annex/`` may import ``hydromodpy/``. The reverse is forbidden.
5. Inside ``data``, ``calibration`` and ``display``, a part imports only what its row
   of the package ``*_layout.yaml`` allows.
6. A solver sub-package reads only the private names it declares itself
   (``test_solver_private_attributes.py``).
7. A new edge that violates the matrix is a regression. Propose the change before you
   touch the code.

**Held by convention.** No test fails on these, so a reviewer holds them.

- The two MODFLOW backends, ``solver/modflow6/`` and ``solver/modflow_nwt/``, do not
  import each other. What they share lives in ``solver/modflow_common/`` and
  ``solver/modflow_grid/``. The matrix sees ``solver`` as one layer, so it cannot
  check this.
- A leading underscore means private to the owning package. The linter enforces it
  for ``data/`` and ``display/`` (rule ``SLF001``); elsewhere it is a review matter.

.. include:: layer-matrix.partial.rst

Special layers
--------------

``catalog``
   Public V1 facade over cache, project catalog and global index. It may import
   ``data`` and ``results`` to wrap their stores. The reverse edge is forbidden.

``project``
   Public object-oriented facade. It binds workflow and calibration launchers to
   ``Project``, so that lower layers do not depend on the facade.

``cli``
   The ``hmp`` command. Only ``hydromodpy/__main__.py`` imports it, which
   ``test_cli_boundary.py`` checks.

How CI checks the matrix
------------------------

``tests/unit/architecture/test_layer_matrix.py`` parses every Python file of
``hydromodpy/`` and asserts that each edge is allowed or tolerated. It also checks
that the matrix and the package list agree and that every declared layer has a page
in :doc:`packages/index`. The other files of the folder hold the contracts listed in
:doc:`generated/guards`. When one fails, follow
:doc:`how-to/fix-an-architecture-gate`.

When a refactor needs a new edge
--------------------------------

1. Look for an intermediary layer that already carries the dependency.
2. If none fits, propose the change in an issue before touching code.
3. Change the YAML and the prose together, and say why in the tolerance entry.
4. Never add a tolerance silently.

See also
--------

- :doc:`packages/index` for the role of each layer.
- :doc:`mental-model` for the runtime flow the matrix shapes.

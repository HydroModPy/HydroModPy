Layered Architecture
====================

HydroModPy is built as a strict layered DAG. Every top-level subpackage
of ``hydromodpy/`` belongs to one layer and may only import from the
targets declared in ``tests/unit/architecture/layer_matrix.yaml``.

The YAML file is the normative contract, and the tables below are
generated from it by ``tools/doc_contracts.py`` at every build, so they
cannot drift from it. The CI gate reads the same YAML through
``tests/unit/architecture/test_layer_matrix.py``.

Ports and adapters at the storage edge
--------------------------------------

The V1 storage contract is DuckDB-first, not backend-agnostic in every
runtime path. The project catalog uses
:class:`~hydromodpy.results.catalog.ports.CatalogBackend`, with
``DuckDBBackend`` as the in-tree implementation. The data cache uses a
separate DuckDB cache adapter. CLI diagnostics, migration runners and
portable-package snapshots may open DuckDB directly when documented as
exceptions in :doc:`storage-layout`.

Field readers go through ``hmp.read`` which dispatches to Zarr or
Parquet stores via the field registry. See
:doc:`/architecture/packages/results` for the Python surface.

The rules
---------

1. One layer per top-level subpackage. Cross-edges that violate the
   matrix fail CI.
2. One-way dependencies only. No cycles, even under ``TYPE_CHECKING``.
3. ``core`` is the kernel leaf. It must not import any sibling layer.
4. Each MODFLOW backend is independent. ``solver/modflow6/`` and
   ``solver/modflow_nwt/`` never cross-import.
5. ``hydromodpy_annex/`` may import ``hydromodpy/``. The reverse is
   forbidden.
6. Cross-package imports of underscored modules are forbidden. Leading
   underscore means private to the owning package.
7. A new edge that violates the matrix is a regression.

.. include:: layer-matrix.partial.rst

Special layers
--------------

``catalog``
   Public V1 facade over cache, project catalog and global index. It
   may import ``data`` and ``results`` to wrap their stores. The reverse
   edge is forbidden.

``project``
   Public object-oriented facade. It sits above the matrix like ``cli``
   so lower layers do not depend on ``Project``.

How CI checks the matrix
------------------------

``tests/unit/architecture/test_layer_matrix.py`` parses every Python
file in ``hydromodpy/`` and asserts each edge is either allowed or
tolerated. It also checks that every declared package has a per-package
architecture page.

When refactoring across layers
------------------------------

If a refactor needs a new edge that the matrix forbids:

1. Look for an existing intermediary layer.
2. If none fits, propose the change before touching code.
3. Update the YAML and the prose together.
4. Never add a tolerance silently.

See also
--------

- :doc:`package-layout` for the role of each layer.
- :doc:`overview/mental-model-and-design-choices` for the runtime flow
  that the matrix shapes.
- :doc:`overview/code-reading-guide` for the package-by-package
  reading order.

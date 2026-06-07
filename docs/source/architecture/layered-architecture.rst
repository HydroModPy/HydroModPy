Layered Architecture
====================

HydroModPy is built as a strict layered DAG. Every top-level subpackage
of ``hydromodpy/`` belongs to one layer and may only import from the
targets declared in ``tests/unit/architecture/layer_matrix.yaml``.

The YAML file is the normative contract. This page mirrors the current
state for readers, but the CI gate reads the YAML directly through
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

Layer matrix
------------

.. list-table::
   :header-rows: 1
   :widths: 16 84

   * - Source layer
     - Allowed import targets
   * - ``<root>``
     - ``<root>``, ``core``, ``schema``, ``config``, ``physics``,
       ``data``, ``spatial``, ``simulation``, ``solver``,
       ``calibration``, ``results``, ``display``, ``analysis``,
       ``reporting``, ``workflow``, ``catalog``, ``cli``
   * - ``core``
     - ``core``
   * - ``schema``
     - ``core``, ``schema``, ``config``
   * - ``config``
     - ``core``, ``schema``, ``config``, ``physics``, ``data``,
       ``spatial``, ``simulation``, ``solver``, ``calibration``,
       ``results``, ``display``, ``analysis``, ``reporting``,
       ``workflow``
   * - ``physics``
     - ``core``, ``schema``, ``physics``
   * - ``data``
     - ``core``, ``schema``, ``data``, ``spatial``
   * - ``spatial``
     - ``core``, ``schema``, ``spatial``
   * - ``simulation``
     - ``core``, ``schema``, ``physics``, ``spatial``, ``data``,
       ``simulation``
   * - ``solver``
     - ``core``, ``schema``, ``physics``, ``spatial``, ``solver``,
       ``simulation``
   * - ``calibration``
     - ``core``, ``schema``, ``physics``, ``data``, ``spatial``,
       ``solver``, ``simulation``, ``calibration``, ``results``
   * - ``results``
     - ``core``, ``schema``, ``config``, ``results``, ``spatial``
   * - ``display``
     - ``core``, ``schema``, ``results``, ``display``
   * - ``analysis``
     - ``core``, ``schema``, ``physics``, ``data``, ``results``,
       ``display``, ``analysis``
   * - ``reporting``
     - ``core``, ``schema``, ``config``, ``results``, ``display``,
       ``analysis``, ``reporting``
   * - ``workflow``
     - ``core``, ``schema``, ``config``, ``physics``, ``data``,
       ``spatial``, ``simulation``, ``solver``, ``calibration``,
       ``results``, ``display``, ``analysis``, ``reporting``,
       ``workflow``
   * - ``validity_frame``
     - ``validity_frame``
   * - ``catalog``
     - ``core``, ``schema``, ``data``, ``results``, ``catalog``
   * - ``project``
     - ``core``, ``schema``, ``config``, ``physics``, ``data``,
       ``spatial``, ``simulation``, ``solver``, ``calibration``,
       ``results``, ``display``, ``analysis``, ``reporting``,
       ``workflow``, ``catalog``, ``project``
   * - ``cli``
     - ``<root>``, ``core``, ``schema``, ``config``, ``physics``,
       ``data``, ``spatial``, ``simulation``, ``solver``,
       ``calibration``, ``results``, ``display``, ``analysis``,
       ``reporting``, ``workflow``, ``catalog``, ``project``, ``cli``

Documented tolerances
---------------------

Tolerances live in ``layer_matrix.yaml`` and must carry a rationale.
They are temporary or deliberately narrow edges. A contributor should
tighten them when the underlying edge disappears.

Current tolerances cover:

- root lazy resolution of ``project``;
- comparison exports reusing display helpers;
- comparison orchestration writing an HTML report;
- ``FlowConfig`` embedding a spatial discriminated union;
- core time validation using flow-regime semantics;
- read-only cross-DB bridges between data cache and results catalog.

Special layers
--------------

``catalog``
   Public V1 facade over cache, project catalog and global index. It
   may import ``data`` and ``results`` to wrap their stores. The reverse
   edge is forbidden.

``project``
   Public object-oriented facade. It sits above the matrix like ``cli``
   so lower layers do not depend on ``Project``.

``validity_frame``
   Experimental observability tooling. It is installed with the package
   but isolated from the modeling DAG and is not a stable V1 public API.

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

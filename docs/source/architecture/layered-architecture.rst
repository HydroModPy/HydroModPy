Layered Architecture
====================

HydroModPy is built as a strict layered DAG. Every subpackage of
``hydromodpy/`` belongs to one layer and may only import from a
restricted set of other layers. The matrix below is the v1 contract
checked by ``tests/unit/architecture/test_layer_matrix.py`` against
``tests/unit/architecture/layer_matrix.yaml``.

The rules
---------

1. **One layer per subpackage.** Cross-edges that violate the matrix
   fail CI.
2. **One-way dependencies only.** No cycles, even under
   ``TYPE_CHECKING``.
3. **``core`` is the kernel leaf.** It must not import any sibling
   layer.
4. **Each MODFLOW backend is independent.** ``solver/modflow6/`` and
   ``solver/modflow_nwt/`` never cross-import; shared helpers live in
   ``solver/modflow_common/`` and ``solver/modflow_grid/``.
5. **``hydromodpy_annex/`` may import ``hydromodpy/``.** The reverse
   is forbidden.
6. **Cross-package imports of underscored modules are forbidden.**
   Leading underscore means truly private to the owning package.
7. **A new edge that violates the matrix is a regression.** When in
   doubt, ask before adding it.

Layer matrix
------------

.. list-table::
   :header-rows: 1
   :widths: 14 86

   * - Source layer
     - Allowed import targets
   * - ``core``
     - ``core``
   * - ``schema``
     - ``core``, ``schema``, ``config``
   * - ``config``
     - ``core``, ``schema``, ``config``, ``physics``, ``data``,
       ``spatial``, ``simulation``, ``solver``, ``calibration``,
       ``results``, ``display``, ``analysis``, ``workflow``
   * - ``physics``
     - ``core``, ``schema``, ``physics``
   * - ``data``
     - ``core``, ``schema``, ``data``
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
       ``solver``, ``simulation``, ``calibration``
   * - ``results``
     - ``core``, ``schema``, ``config``, ``results``
   * - ``display``
     - ``core``, ``schema``, ``results``, ``display``
   * - ``analysis``
     - ``core``, ``schema``, ``data``, ``results``, ``analysis``
   * - ``workflow``
     - ``core``, ``schema``, ``config``, ``physics``, ``data``,
       ``spatial``, ``simulation``, ``solver``, ``calibration``,
       ``results``, ``display``, ``analysis``, ``workflow``
   * - ``cli``
     - everything (top-level dispatcher)
   * - ``<root>`` (top-level helpers in ``hydromodpy/``)
     - everything

The full machine-readable matrix lives in
``tests/unit/architecture/layer_matrix.yaml``.

Documented tolerances
---------------------

A few legacy edges are tolerated until further refactoring. Each one
must point to a documented rationale; CI will fail if a tolerance is
removed and the underlying edge still exists.

.. list-table::
   :header-rows: 1
   :widths: 14 14 72

   * - Source
     - Target
     - Reason
   * - ``data``
     - ``spatial``
     - Geology field bridging.
   * - ``calibration``
     - ``results``
     - Calibration reads the catalog at planning time.
   * - ``simulation``
     - ``solver``
     - Simulation queries the solver registry.
   * - ``results``
     - ``spatial``
     - Results stores spatial indices.
   * - ``analysis``
     - ``physics``
     - History contract.
   * - ``calibration``
     - ``<root>``
     - Trial promotion launches the public ``Project`` facade.
   * - ``cli``
     - ``<root>``
     - CLI dispatch delegates to the public ``Project`` facade.
   * - ``workflow``
     - ``<root>``
     - Sweep helper accepts ``Project`` facade instances.
   * - ``analysis``
     - ``display``
     - Comparison exports reuse plot mesh loading.
   * - ``analysis``
     - ``solver``
     - Comparison runtime resolves solver families.
   * - ``results``
     - ``analysis``
     - ``Run`` exposes stream-network diagnostics.
   * - ``physics``
     - ``spatial``
     - ``FlowConfig`` embeds spatial ``FieldSection`` discriminated
       union.

Exempt files
------------

A short list of bootstrap shims and runnable case entry points are
exempt from the layer rule:

- ``hydromodpy/__init__.py``
- ``hydromodpy/_bootstrap.py``
- ``hydromodpy/__main__.py``
- ``hydromodpy/project.py``
- ``hydromodpy/spatial/domain/cases/run_domain_case.py``
- ``hydromodpy/spatial/geographic/cases/reference_catchment_delineation_case/run_case.py``

How CI checks the matrix
------------------------

``tests/unit/architecture/test_layer_matrix.py`` walks every Python
file in ``hydromodpy/``, parses the imports, and asserts each edge is
either in the allowed-targets list or in the documented-tolerance
list. A new violation fails the unit test tier.

When refactoring across layers
------------------------------

If a refactor needs a new edge that the matrix forbids:

1. Look for an existing intermediary layer (often ``core`` or
   ``schema`` is enough).
2. If none fits, propose the change before touching code: tighten the
   matrix, document the rationale, then update the YAML and the test.
3. Never add a tolerance silently. Tolerances exist to be tracked and
   removed, not to be accumulated.

See also
--------

- :doc:`package-layout` for the role of each layer.
- :doc:`overview/mental-model-and-design-choices` for the runtime flow
  that the matrix shapes.
- :doc:`overview/code-reading-guide` for the package-by-package
  reading order.

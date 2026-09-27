display
=======

``hydromodpy.display`` is the solver-agnostic figure layer. It wraps
matplotlib through a registered catalog of named figures consumable
from ``hmp.figure``, ``hmp viz show``, ``hmp viz gallery``, and the
``[display]`` TOML section. Its map, its import rules and where to add
what are ``hydromodpy/display/README.md``, enforced by
``tests/unit/architecture/display_layout.yaml`` and
``tests/unit/architecture/test_package_layouts.py``.

Sub-modules
-----------

- ``display/figure.py`` -- ``FigureSpec`` dataclass, ``Figure``
  Protocol, and ``BaseFigure`` ABC. Concrete figures inherit from
  ``BaseFigure`` and decorate themselves with ``@register``.
- ``display/figure_registry.py`` -- registry, ``register`` decorator,
  ``get(name)``, ``list_figures()``, ``names()``.
- ``display/figures/`` -- one module per named figure. Auto-discovery
  through ``pkgutil.iter_modules`` in
  ``display/figures/__init__.py``.
- ``display/maps/`` -- the map tools the figures share: map axes, mesh
  geometry, one value per face, named overlays, sections, and ``geo/``
  (scale bar and north arrow on metric axes,
  ``project_gdf_for_metric_operations``).
- ``display/runs.py`` -- the figures of a run: ``render_figures_for_run``
  for the ``[display]`` list, ``render_figure`` for one figure,
  ``figure_availability`` for what a run supports.
- ``display/overview/`` -- composed overview report rendering used
  by the ``[overview]`` workflow.
- ``display/report_blocks/`` -- shared static HTML block primitives
  used by block-based reports. It owns the generic dataclasses,
  renderer, level navigation, per-block level switches, relative
  artifact links, and missing-figure placeholders.
- ``display/catchment_report/`` -- generic watershed report pipeline
  driven by ``hmp report catchment`` and rendered through
  ``display/report_blocks``.
- ``display/config.py`` -- ``DisplayConfig`` Pydantic model for
  the ``[display]`` TOML section.
- ``display/style.py`` -- how every figure looks: themes, banned and
  preferred colormaps, legend placement.
- ``display/quicklook/`` -- a quick look at data outside the figure
  catalogue: ``hmp.viz.show`` (``viz.py``, with datashader in
  ``scalable.py``) and animations of PNG already rendered
  (``animation.py``). ``hmp viz`` does not use them.

Block HTML Reports
------------------

``display/report_blocks`` is the common renderer for static reports
composed from reusable blocks. The key contract is that workflow code
builds ``ReportBlock`` objects, while the shared renderer writes the
HTML page. Domain-specific report modules should keep their scientific
logic in their own ``blocks.py`` files and call:

- ``write_report_page(...)`` for one static page;
- ``write_report_page_with_block_variants(...)`` for a page where
  each block can switch between ``compact``, ``standard`` and
  ``audit`` detail.

The renderer is currently used by overview reporting, site-selection
review reports, the catchment report pipeline, and the
network/transient calibration diagnostic page.

Figure inventory
----------------

The inventory is generated from the registry into
:doc:`/user_guide/figures`, grouped by ``FigureSpec.kind``, with the title
and the requirements of each figure. ``hmp viz list`` prints the live list,
and ``hmp viz list --run <sim_id>`` says which figures one run supports and
why not the others.

Figure contract
---------------

.. code-block:: python

   @dataclass(frozen=True, slots=True)
   class FigureSpec:
       name: str
       title: str
       former_names: tuple[str, ...] = ()
       kind: FigureKind = "spatial"   # spatial, section, timeseries, balance,
                                      # particles, table, comparison, animation
       required_fields: tuple[str, ...] = ()
       optional_fields: tuple[str, ...] = ()
       required_tables: tuple[str, ...] = ()
       required_solvers: tuple[str, ...] = ()
       default_figsize: tuple[float, float] = (7.0, 5.0)


   class BaseFigure(ABC):
       """Implements plot() boilerplate (subplots + render + save)."""
       spec: FigureSpec

       @abstractmethod
       def render(self, sim: Run, ax: Axes, **opts) -> Axes: ...

       def unavailable_reason(self, sim: Run) -> str | None: ...

A figure a run cannot feed is refused by ``unavailable_reason`` with a
sentence: skipped by ``[display].figures``, refused by ``hmp viz show`` and
``hmp.figure``, and marked with its reason by ``hmp viz list --run``.

The ``@register`` decorator places the class in the global registry
keyed by ``spec.name``.

Key public symbols
------------------

- ``hydromodpy.display.{get, list_figures, names}``
- ``hydromodpy.display.figure.{FigureSpec, BaseFigure}``
- ``hydromodpy.display.figure_registry.register``
- ``hydromodpy.display.runs.{render_figures_for_run, render_figure,
  figure_availability}``
- ``hydromodpy.display.config.DisplayConfig``
- ``hydromodpy.display.report_blocks.{ReportBlock, ReportMetric,
  ReportFigure, ReportTable, ReportLink}``
- ``hydromodpy.display.report_blocks.{write_report_page,
  write_report_page_with_block_variants}``

Recommended reading path
------------------------

1. ``hydromodpy/display/figure.py`` for the contract.
2. ``hydromodpy/display/figure_registry.py`` for the registry.
3. ``hydromodpy/display/figures/__init__.py`` for the auto-discovery.
4. One simple figure such as
   ``hydromodpy/display/figures/hydrograph.py``.
5. One spatial figure such as
   ``hydromodpy/display/figures/piezometric_map.py``.
6. ``hydromodpy/display/report_blocks/model.py`` and
   ``hydromodpy/display/report_blocks/html.py`` for the static HTML
   block contract.
7. ``hydromodpy/display/catchment_report/builder.py`` for a complete
   block-based report producer.

Layer-matrix neighbours
-----------------------

- Allowed targets: ``core``, ``schema``, ``results``, ``display``.
- Allowed sources: the root facade (``<root>``), ``config``, ``analysis``,
  ``reporting``, ``workflow``, ``project`` and ``cli``, each through the
  modules the ``public`` list of ``display_layout.yaml`` names;
  ``calibration`` through a tolerance of ``layer_matrix.yaml``, for
  ``hydromodpy.display.report_blocks`` only.
- ``display`` must not import ``data``, ``simulation``, ``solver``,
  ``calibration``. Reach data through ``Run`` (``run.field``,
  ``run.timeseries``, ``run.budget``) or a module function of ``results``.
- Inside the package, the import rules are
  ``hydromodpy/display/README.md`` ("Import rules").

See also
--------

- :doc:`/user_guide/figures` -- user-facing figure catalog.
- :doc:`/architecture/how-to/add-a-figure` -- step-by-step recipe.
- :doc:`/architecture/how-to/add-a-block-html-report` -- recipe for
  adding a block-based static HTML report.
- :doc:`results` for the ``Run`` API the figures consume.

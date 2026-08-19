display
=======

``hydromodpy.display`` is the solver-agnostic figure layer. It wraps
matplotlib through a registered catalog of named figures consumable
from ``Run.plot``, ``hmp viz show``, ``hmp viz gallery``, and the
``[display]`` TOML section.

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
- ``display/geo/`` -- shared geographic plotting helpers (basemaps,
  CRS-aware axes, scalebar, north arrow).
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
- ``display/theme.py`` -- shared style / colormap selection.

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

Figure inventory (45 today)
---------------------------

Grouped by ``FigureSpec.kind``. ``hmp viz list`` prints the live list;
this page is a reading aid, not the source of truth.

Spatial (8): ``concentration_map``, ``mesh_map``, ``piezometric_map``,
``recharge_map``, ``seepage_map``, ``sfr_reach_network``,
``simulated_active_network``, ``watertable_depth_map``.

Section (1): ``cross_section``.

Time series (8): ``calibration_convergence``, ``calibration_trace``,
``duration_curve``, ``hydrograph``, ``recession``,
``seasonal_boxplot``, ``sfr_longitudinal_profile``,
``sfr_reach_timeseries``.

Balance (2): ``flux_timeseries``, ``water_budget``.

Comparison (22): ``calibration_landscape``,
``calibration_objective_surface``, ``calibration_pairplot``,
``calibration_posterior``, ``conditioning_impact_map``,
``difference_map``, ``ensemble_band``, ``hydrograph_sim_obs``,
``hydrographic_network_comparison``,
``hydrographic_network_generated``,
``hydrographic_network_generated_extra_only``,
``hydrographic_network_reference``,
``hydrographic_network_reference_missing_only``,
``lake_abacus_comparison``, ``lake_stage_sim_obs``,
``lake_volume_sim_obs``, ``piezo_timeseries_sim_obs``, ``residuals``,
``scatter_one_to_one``, ``side_by_side``,
``simulated_active_network_reference_overlay``,
``watershed_id_card``.

Table (3): ``piper_diagram``, ``schoeller_diagram``,
``stiff_diagram``.

Particles (1): ``particle_tracks``.

Figure contract
---------------

.. code-block:: python

   @dataclass(frozen=True)
   class FigureSpec:
       name: str
       title: str
       kind: str                     # "spatial" | "timeseries" | "balance" | "calibration" | ...
       required_fields: tuple[str, ...]
       required_tables: tuple[str, ...]
       default_figsize: tuple[float, float]


   class BaseFigure(ABC):
       """Implements plot() boilerplate (subplots + render + save)."""
       spec: ClassVar[FigureSpec]

       @abstractmethod
       def render(self, sim: Run, ax: Axes, **opts) -> Axes: ...

The ``@register`` decorator places the class in the global registry
keyed by ``spec.name``.

Key public symbols
------------------

- ``hydromodpy.display.{get, list_figures, names}``
- ``hydromodpy.display.figure.{FigureSpec, BaseFigure}``
- ``hydromodpy.display.figure_registry.register``
- ``hydromodpy.display.theme.plot_params``
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
- Allowed sources: ``analysis``, ``reporting``, ``workflow``,
  ``project`` and ``cli``.
- ``display`` must not import ``data``, ``simulation``, ``solver``,
  ``calibration``. Reach data through ``Run`` (``run.field``,
  ``run.timeseries``, ``run.budget``).

See also
--------

- :doc:`/user_guide/figures` -- user-facing figure catalog.
- :doc:`/architecture/how-to/add-a-figure` -- step-by-step recipe.
- :doc:`/architecture/how-to/add-a-block-html-report` -- recipe for
  adding a block-based static HTML report.
- :doc:`results` for the ``Run`` API the figures consume.

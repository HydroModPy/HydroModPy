display
=======

``hydromodpy.display`` is the solver-agnostic figure layer. It wraps
matplotlib through a registered catalog of named figures consumable
from ``Run.plot``, ``hmp display``, and the ``[display]`` TOML
section.

Sub-modules
-----------

- ``display/figure.py`` -- ``FigureSpec`` dataclass, ``Figure``
  Protocol, and ``BaseFigure`` ABC. Concrete figures inherit from
  ``BaseFigure`` and decorate themselves with ``@register``.
- ``display/catalog.py`` -- registry, ``register`` decorator,
  ``get(name)``, ``list_figures()``, ``names()``.
- ``display/figures/`` -- one module per named figure. Auto-discovery
  through ``pkgutil.iter_modules`` in
  ``display/figures/__init__.py``.
- ``display/geo/`` -- shared geographic plotting helpers (basemaps,
  CRS-aware axes, scalebar, north arrow).
- ``display/overview/`` -- composed overview report rendering used
  by the ``[overview]`` workflow.
- ``display/config.py`` -- ``DisplayConfig`` Pydantic model for
  the ``[display]`` TOML section.
- ``display/theme.py`` -- shared style / colormap selection.

Figure inventory (33 today)
---------------------------

Spatial: ``piezometric_map``, ``recharge_map``, ``seepage_map``,
``concentration_map``, ``side_by_side_map``, ``difference_map``,
``cross_section``, ``hydrographic_network``,
``hydrographic_network_comparison``, ``simulated_active_network``,
``watershed_id_card``, ``residuals``.

Time series: ``hydrograph``, ``hydrograph_sim_obs``,
``piezo_timeseries_sim_obs``, ``duration_curve``,
``seasonal_boxplot``, ``recession``, ``ensemble_band``.

Balance: ``water_budget``.

Calibration: ``calibration_convergence``,
``calibration_landscape``, ``calibration_objective_surface``,
``calibration_pairplot``, ``calibration_posterior``,
``calibration_trace``.

Hydrochemistry: ``piper_diagram``, ``schoeller_diagram``,
``stiff_diagram``.

Particle / scatter: ``particle_tracks``, ``scatter_one_to_one``.

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
- ``hydromodpy.display.catalog.register``
- ``hydromodpy.display.theme.plot_params``
- ``hydromodpy.display.config.DisplayConfig``

Recommended reading path
------------------------

1. ``hydromodpy/display/figure.py`` for the contract.
2. ``hydromodpy/display/catalog.py`` for the registry.
3. ``hydromodpy/display/figures/__init__.py`` for the auto-discovery.
4. One simple figure such as
   ``hydromodpy/display/figures/hydrograph.py``.
5. One spatial figure such as
   ``hydromodpy/display/figures/piezometric_map.py``.

Layer-matrix neighbours
-----------------------

- Allowed targets: ``core``, ``schema``, ``results``, ``display``.
- Allowed sources: ``analysis`` (tolerance for comparison exports),
  ``workflow``, ``cli``, top-level facade.
- ``display`` must not import ``data``, ``simulation``, ``solver``,
  ``calibration``. Reach data through ``Run`` (``run.field``,
  ``run.timeseries``, ``run.budget``).

See also
--------

- :doc:`/user_guide/figures` -- user-facing figure catalog.
- :doc:`/architecture/how-to/add-a-figure` -- step-by-step recipe.
- :doc:`results` for the ``Run`` API the figures consume.

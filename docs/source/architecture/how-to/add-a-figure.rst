Add a Figure
============

Figures live in ``hydromodpy.display`` and are auto-discovered through
``display/figures/__init__.py`` (``pkgutil.iter_modules``). Today 33
figures ship: ``hydrograph``, ``piezometric_map``, ``water_budget``,
``calibration_convergence``, ``hydrographic_network_comparison``,
``simulated_active_network``, ``side_by_side_map``, etc.

Contract
--------

Every figure is a ``BaseFigure`` subclass decorated with
``@register``. It exposes a ``FigureSpec`` dataclass and a ``render``
method:

.. code-block:: python

   # hydromodpy/display/figure.py
   @dataclass(frozen=True)
   class FigureSpec:
       name: str
       title: str
       kind: str                          # "spatial" | "timeseries" | "balance" | "calibration" | ...
       required_fields: tuple[str, ...]
       required_tables: tuple[str, ...]
       default_figsize: tuple[float, float]


   class Figure(Protocol):
       spec: ClassVar[FigureSpec]

       def render(self, sim: "Run", ax: "Axes", **opts) -> "Axes": ...
       def plot(self, sim: "Run", *, save_path: Path | None, **opts) -> "Figure": ...

   class BaseFigure(ABC):
       """Implements ``plot()`` boilerplate (subplots + render + save)."""

Files to create
---------------

A new figure called ``my_figure``:

.. code-block:: text

   hydromodpy/display/figures/my_figure.py

Skeleton:

.. code-block:: python

   from matplotlib.axes import Axes

   from hydromodpy.display.catalog import register
   from hydromodpy.display.figure import BaseFigure, FigureSpec
   from hydromodpy.results.run import Run


   @register
   class MyFigure(BaseFigure):
       spec = FigureSpec(
           name="my_figure",
           title="My figure",
           kind="spatial",
           required_fields=("head",),
           required_tables=(),
           default_figsize=(7.0, 5.0),
       )

       def render(self, sim: Run, ax: Axes, **opts) -> Axes:
           timestep = opts.get("timestep", -1)
           head = sim.field("head", timestep=timestep)
           im = ax.imshow(head, origin="lower")
           ax.set_title(self.spec.title)
           ax.figure.colorbar(im, ax=ax, label="head [m]")
           return ax

The base ``BaseFigure.plot`` method handles the full lifecycle:

1. resolve ``required_fields`` / ``required_tables`` against ``Run``;
2. create the matplotlib subplots with ``default_figsize``;
3. call ``render``;
4. optionally save to ``save_path``.

Pick the right ``kind``
-----------------------

The ``kind`` field hints the layout used by composed reports:

- ``spatial`` -- map-style plots (``imshow``, ``pcolormesh``,
  ``tripcolor``).
- ``timeseries`` -- line plots over the simulation period.
- ``balance`` -- water budget bar charts.
- ``calibration`` -- convergence, posterior, landscape views.
- ``compare`` -- side-by-side grids.

Add a new ``kind`` only when the existing layouts cannot host the
view.

Required fields and tables
--------------------------

Listing requirements explicitly lets the registry pre-flight the
plot before reading the disk:

- ``required_fields`` -- Zarr dataset names that
  ``Run.field(...)`` must be able to load.
- ``required_tables`` -- Parquet-backed DuckDB tables (``timeseries``,
  ``budgets``, ``mass_balance``).

A figure that depends on an optional product should declare it and
fall back gracefully in ``render``.

Auto-discovery
--------------

``display/figures/__init__.py`` walks every ``.py`` module in the
folder with ``pkgutil.iter_modules`` and imports it. Any
``@register``-decorated class becomes part of the global catalog. No
extra wiring is needed.

Render from CLI and TOML
------------------------

Once registered, the figure is reachable from:

.. code-block:: bash

   hmp display <sim_id> --figure my_figure
   hmp display run.toml --session <session_id> --figure my_figure  # calibration

And from TOML:

.. code-block:: toml

   [display]
   figures = ["piezometric_map", "water_budget", "my_figure"]

Tests to add
------------

- **Unit** under ``tests/unit/display/figures/`` against a synthetic
  ``Run`` fixture: assert the figure produces a non-empty axes and
  honours ``required_fields`` / ``required_tables``.
- **Image regression** (optional): commit a small reference PNG and
  compare with ``matplotlib.testing.compare_images``.

Pitfalls flagged by the layer matrix
------------------------------------

- ``display`` may import ``core``, ``schema``, ``results``, and
  ``display``. It must **not** import ``data``, ``simulation``,
  ``solver``, ``calibration``, ``analysis``, or ``workflow``.
- The ``analysis -> display`` tolerance is reserved for comparison
  exports. Do not push display logic into ``analysis``.
- Reach the data through ``Run`` (``run.field``, ``run.timeseries``,
  ``run.budget``), never through raw Zarr / DuckDB calls inside the
  figure module.

See also
--------

- :doc:`../packages/display` for the figure registry and the existing
  inventory.
- :doc:`add-an-exporter` if your output is a file format rather than
  a matplotlib figure.
- :doc:`/user_guide/figures` for the user-facing figure catalog.

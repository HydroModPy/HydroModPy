Add a Figure
============

Figures live in ``hydromodpy.display`` and are auto-discovered through
``display/figures/__init__.py`` (``pkgutil.iter_modules``). ``hmp viz list``
prints every registered figure, and :doc:`/user_guide/figures` carries the
generated inventory: ``hydrograph``, ``piezometric_map``, ``water_budget``,
``calibration_convergence``, ``hydrographic_network_comparison``,
``simulated_active_network``, ``side_by_side``, and the others. The map of the
package, with its import rules, is ``hydromodpy/display/README.md``.

Contract
--------

Every figure is a ``BaseFigure`` subclass decorated with
``@register``. It exposes a ``FigureSpec`` dataclass and a ``render``
method:

.. code-block:: python

   # hydromodpy/display/figure.py
   @dataclass(frozen=True, slots=True)
   class FigureSpec:
       name: str
       title: str
       former_names: tuple[str, ...] = ()
       kind: FigureKind = "spatial"         # one of the eight kinds below
       required_fields: tuple[str, ...] = ()
       optional_fields: tuple[str, ...] = ()
       required_tables: tuple[str, ...] = ()
       required_solvers: tuple[str, ...] = ()
       default_figsize: tuple[float, float] = (7.0, 5.0)


   class Figure(Protocol):
       spec: FigureSpec

       def render(self, sim: "Run", ax: "Axes", **opts) -> "Axes": ...
       def plot(self, sim: "Run", **opts) -> "Figure": ...
       def unavailable_reason(self, sim: "Run") -> str | None: ...

   class BaseFigure(ABC):
       """Implements ``plot()`` boilerplate (subplots + render + save)."""

Files to create
---------------

A new figure called ``my_figure``:

.. code-block:: text

   hydromodpy/display/figures/my_figure.py

The file name must not start with ``_``: discovery skips those, which is
where helpers shared by several figures live.

A map of one value per mesh face needs no ``render``: subclass
``ScalarFaceMap`` and declare the field. Model: ``figures/piezometric_map.py``.

.. code-block:: python

   from hydromodpy.display.figure import FigureSpec
   from hydromodpy.display.figure_registry import register
   from hydromodpy.display.figures._scalar_face_map import ScalarFaceMap


   @register
   class PiezometricMap(ScalarFaceMap):
       spec = FigureSpec(
           name="piezometric_map",
           title="Water-table elevation",
           kind="spatial",
           required_fields=("watertable_elevation",),
       )
       default_cmap = "viridis"
       default_overlays = ("watershed", "outlet")

Anything else is a ``BaseFigure`` with a ``render`` that draws on the axes it
gets. Skeleton:

.. code-block:: python

   from matplotlib.axes import Axes

   from hydromodpy.display.figure_registry import register
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

The base ``BaseFigure.plot`` method creates the matplotlib subplots with
``default_figsize``, calls ``render`` and, when asked, saves the PNG with its
provenance. Whether the figure applies to a run is decided before, by
``unavailable_reason``: ``[display].figures`` skips a figure it refuses, and
``hmp viz show`` and ``hmp.figure`` refuse it with the same sentence.

Pick the right ``kind``
-----------------------

``kind`` is the plotting family, not the hydrological domain, and takes one
of the eight values of ``FigureKind``:

- ``spatial`` -- a map (one value per face, a network, a raster).
- ``section`` -- a field sampled along a line.
- ``timeseries`` -- line plots over the simulation period.
- ``balance`` -- water budget and mass balance.
- ``particles`` -- pathlines and residence times.
- ``table`` -- diagrams of samples (hydrochemistry).
- ``comparison`` -- simulated against observed, or one run against another.
- ``animation`` -- a sequence of frames.

``hmp viz list --kind <kind>`` filters on it.

Required fields and tables
--------------------------

Listing requirements explicitly lets the registry pre-flight the
plot before reading the disk:

- ``required_fields`` -- Zarr dataset names that
  ``Run.field(...)`` must be able to load. Missing one makes the figure
  UNAVAILABLE: the gallery skips it and says which field is absent.
- ``optional_fields`` -- fields the figure reads when they are there. They
  are turned on for a run that asks for the figure, exactly like a required
  one, but their absence does not make the figure unavailable: the figure
  refuses in its own words instead, which is what a map over several
  boundary packages needs when a run carries two of six.
- ``required_tables`` -- Parquet-backed DuckDB tables (``timeseries``,
  ``budgets``, ``mass_balance``).

A figure that reads an optional product declares it in ``optional_fields``
and says in ``unavailable_reason`` what it looked for and how to enable it.

A need ``spec`` cannot express (a network, a DEM raster, hydrochemistry, the
series of a stream reach, a lake or a piezometer) goes into an
``unavailable_reason`` override that calls the base first and returns a
sentence. ``render`` may then assume the data is there. It never raises for
missing data and never draws a placeholder. Model:
``figures/lake_abacus_comparison.py``.

.. code-block:: python

   def unavailable_reason(self, sim: Run) -> str | None:
       reason = super().unavailable_reason(sim)
       if reason is not None:
           return reason
       try:
           run_lake_abacus(sim)
       except KeyError:
           return "run holds no lake abacus"
       return None

``hmp viz list --run <sim_id>`` prints, for each figure, whether a run
supports it or the sentence that says why not.

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

   hmp viz show <sim_ref> my_figure
   hmp viz gallery project.toml --only my_figure

And from TOML:

.. code-block:: toml

   [display]
   figures = ["piezometric_map", "water_budget", "my_figure"]

Tests to add
------------

- **Registry**: a line in ``REGISTRY_CONTRACT``
  (``tests/unit/display/test_figure_registry_completeness.py``: class,
  ``kind``, ``required_fields``). The test refuses a figure missing from it.
- **Refusal**: ``tests/unit/display/test_every_figure_refuses_an_empty_run.py``
  runs on every registered figure and fails when one accepts a run that holds
  nothing.
- **Unit** under ``tests/unit/display/`` against a synthetic ``Run``
  fixture: assert the figure produces a non-empty axes.
- **Image regression** (optional): commit a small reference PNG and
  compare with ``matplotlib.testing.compare_images``.

Pitfalls flagged by the layer matrix
------------------------------------

- ``display`` may import ``core``, ``schema``, ``results``, and
  ``display``. It must **not** import ``data``, ``simulation``,
  ``solver``, ``calibration``, ``analysis``, or ``workflow``.
- Inside ``display``, a shared tool never imports ``figures/``;
  ``tests/unit/architecture/display_layout.yaml`` lists who may import whom.
- Reach the data through ``Run`` (``run.field``, ``run.timeseries``,
  ``run.budget``) or a module function of ``results`` that takes the run
  (``results.run.particles``, ``results.calibration_trials``), never through
  raw Zarr / DuckDB calls or a private attribute of the run: ruff rule SLF001
  holds in ``display``.

See also
--------

- :doc:`../packages/display` for the figure registry and the existing
  inventory.
- :doc:`add-an-exporter` if your output is a file format rather than
  a matplotlib figure.
- :doc:`/user_guide/figures` for the user-facing figure catalog.

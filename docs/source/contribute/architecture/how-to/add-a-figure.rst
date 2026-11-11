Add a figure
============

Figures live in ``hydromodpy.display``. Each one is a ``BaseFigure``
subclass that carries its ``spec``, in a public module of
``display/figures/``, and that rule is the whole membership list: the
generated table ``display/figure_table.py`` is what the registry reads.
``hmp config figures`` prints every figure, and :doc:`/understand/reading-results`
carries the generated inventory: ``hydrograph``, ``piezometric_map``,
``water_budget``, ``calibration_convergence``,
``hydrographic_network_comparison``, ``simulated_active_network``,
``side_by_side``, and the others. The map of the package, with its import
rules, is ``hydromodpy/display/README.md``.

Contract
--------

Every figure is a ``BaseFigure`` subclass. It exposes a ``FigureSpec``
dataclass and a ``render`` method, and nothing registers it by hand:
``BaseFigure.__init_subclass__`` takes its name from the ``spec``.

.. code-block:: python

   # hydromodpy/display/figure.py
   @dataclass(frozen=True, slots=True)
   class FigureSpec:
       name: str
       title: str
       former_names: tuple[str, ...] = ()
       kind: FigureKind = "spatial"         # one of the eight kinds below
       subject: FigureSubject = "run"       # "run", "session" or "runset"
       required_fields: tuple[str, ...] = ()
       optional_fields: tuple[str, ...] = ()
       required_tables: tuple[str, ...] = ()
       default_figsize: tuple[float, float] = (7.0, 5.0)


   class Figure(Protocol):
       spec: FigureSpec

       def render(self, subject: Any, ax: "Axes", **opts) -> "Axes": ...
       def plot(self, subject: Any, **opts) -> "Figure": ...
       def unavailable_reason(self, subject: Any) -> str | None: ...

   class BaseFigure(ABC):
       """Implements ``plot()`` boilerplate (subplots + render + save)."""

Files to create
---------------

A new figure called ``my_figure``:

.. code-block:: text

   hydromodpy/display/figures/my_figure.py
   hydromodpy/display/figure_table.py   regenerated, never edited

The file name must not start with ``_``: that is where helpers shared by
several figures live, and the generated table covers only the public
modules.

A map of one value per mesh face needs no ``render``: subclass
``ScalarFaceMap`` and declare the field. Model: ``figures/piezometric_map.py``.

.. code-block:: python

   from hydromodpy.display.figure import FigureSpec
   from hydromodpy.display.figures.scalar_face_map import ScalarFaceMap


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

   from hydromodpy.display.figure import BaseFigure, FigureSpec
   from hydromodpy.results.run import Run


   class MyFigure(BaseFigure):
       spec = FigureSpec(
           name="my_figure",
           title="My figure",
           kind="spatial",
           required_fields=("head",),
           required_tables=(),
           default_figsize=(7.0, 5.0),
       )

       def render(self, subject: Run, ax: Axes, **opts) -> Axes:
           timestep = opts.get("timestep", -1)
           head = subject.field("head", time=timestep)
           im = ax.imshow(head, origin="lower")
           ax.set_title(self.spec.title)
           ax.figure.colorbar(im, ax=ax, label="head [m]")
           return ax

Then regenerate the table:

.. code-block:: bash

   python -m tools.figure_table

``hydromodpy/display/figure_table.py`` holds ``FIGURES`` (each name to its
module and class), ``SUBJECTS``, ``FORMER_NAMES``, ``OPTIONS`` and ``PYTHON_ONLY_OPTIONS``,
literals only. A test regenerates it in memory and fails while the file is
stale, so a figure added without the command never passes the suite.

The ``subject`` field says what the figure draws. ``"run"`` is the default, ``"session"`` is a
calibration session and ``"runset"`` is a set of runs. ``render``, ``plot`` and
``unavailable_reason`` receive the object the subject names. ``display/runs.py`` resolves it once
(``_subject_for``). A session figure asked on a run receives ``Session.of_run(run)`` and the option
``promoted=run``, and a run that no session promoted is refused. A figure that compares a run with
a reference stays a ``"run"`` figure and takes ``reference=``. The generated table also holds
``SUBJECTS``, which maps each name to its subject, and ``hmp config figures`` shows it in a column.

The base ``BaseFigure.plot`` method creates the matplotlib subplots with
``default_figsize``, calls ``render`` and, when asked, saves the PNG with its
provenance. Whether the figure applies to a run is decided before, by
``unavailable_reason``: ``[display].figures`` skips a figure it refuses, and
``hmp show --figure`` and ``Run.figure`` refuse it with the same sentence.

Pick the right ``kind``
-----------------------

``kind`` is the plotting family. It says how the figure is drawn, and the
hydrological domain stays out of it. It takes one
of the eight values of ``FigureKind``:

- ``spatial`` -- a map (one value per face, a network, a raster).
- ``section`` -- a field sampled along a line.
- ``timeseries`` -- line plots over the simulation period.
- ``balance`` -- water budget and mass balance.
- ``particles`` -- pathlines and residence times.
- ``table`` -- diagrams of samples (hydrochemistry).
- ``comparison`` -- simulated against observed, or one run against another.
- ``animation`` -- a sequence of frames.

``hmp config figures --kind <kind>`` filters on it.

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

``hmp config figures --run <sim_id>`` prints, for each figure, whether a run
supports it or the sentence that says why not.

The table, and how a name resolves
----------------------------------

``display/figure_registry.py`` holds ``figures``, the registry of the common
engine, with ``get``, ``resolve``, ``names``, ``list_figures`` and
``figure_option_names``. All of them read the generated table
``figure_table.py``, which imports nothing: answering a name, an old name or
the options of a figure loads no module of ``display/figures/``, and
validating a ``[display]`` section imports no figure module either.
Resolving a name to be drawn imports the one module of that figure.
``resolve`` keeps the former names of the table, with a ``DeprecationWarning``.

Renaming a figure is therefore: change ``spec.name``, put the old name in
``spec.former_names``, regenerate the table. Project files that write the
old name still load, with a warning.

Render from CLI and TOML
------------------------

Once in the table, the figure is reachable from:

.. code-block:: bash

   hmp show <sim_ref> --figure my_figure
   hmp export <sim_ref> --regen figures

And from TOML:

.. code-block:: toml

   # not checked: my_figure is the placeholder figure of this recipe
   [display]
   figures = ["piezometric_map", "water_budget", "my_figure"]

Tests to add
------------

- Table: run ``python -m tools.figure_table``; the freshness test
  regenerates the table in memory and fails while the file is stale.
- Refusal: ``tests/unit/display/test_every_figure_refuses_an_empty_run.py``
  runs on every figure and fails when one accepts a run that holds
  nothing.
- Unit: under ``tests/unit/display/`` against a synthetic ``Run``
  fixture: assert the figure produces a non-empty axes.
- Image regression (optional): commit a small reference PNG and
  compare with ``matplotlib.testing.compare_images``.

Pitfalls flagged by the layer matrix
------------------------------------

- ``display`` may import ``core`` and ``results``. It must **not** import
  ``data``, ``model``, ``solver``, ``calibration``, ``project``, or
  ``workflow``.
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
- :doc:`/understand/reading-results` for the user-facing figure catalog.

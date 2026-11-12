Add a figure
============

Figures live in ``hydromodpy.display``. Each one is a ``BaseFigure`` subclass that
carries its ``spec``, in a public module of ``display/figures/``. The list of shipped
figures is generated, see :doc:`/reference/figures`, and ``hmp config figures`` prints
it too. The modules of the package and its import rules are on :doc:`../packages/display`.

Files to create
---------------

A new figure called ``my_figure`` needs one file and one regenerated file.

.. code-block:: text

   hydromodpy/display/figures/my_figure.py
   hydromodpy/display/figure_table.py   regenerated, never edited

The module name must not start with ``_``. That is where helpers shared by several
figures live, and the generated table covers only the public modules.

A map of one value per mesh face needs no ``render``. It subclasses ``ScalarFaceMap``
and declares the field, like this real figure.

.. literalinclude:: /../../hydromodpy/display/figures/piezometric_map.py
   :pyobject: PiezometricMap

Any other figure is a ``BaseFigure`` with a ``render`` that draws on the axes it gets.

.. code-block:: python

   from matplotlib.axes import Axes

   from hydromodpy.display.figure import BaseFigure, FigureSpec
   from hydromodpy.results.run.view import Run


   class MyFigure(BaseFigure):
       spec = FigureSpec(
           name="my_figure",
           title="My figure",
           kind="spatial",
           required_fields=("head",),
       )

       def render(self, subject: Run, ax: Axes, **opts) -> Axes:
           head = subject.field("head", time=opts.get("timestep", -1))
           im = ax.imshow(head, origin="lower")
           ax.set_title(self.spec.title)
           ax.figure.colorbar(im, ax=ax, label="head [m]")
           return ax

Contract
--------

The figure exposes a ``FigureSpec`` and a ``render`` method. Nothing registers it by
hand, because ``BaseFigure.__init_subclass__`` takes its name from the ``spec``.

.. literalinclude:: /../../hydromodpy/display/figure.py
   :pyobject: FigureSpec

``kind`` is the plotting family, so it says how the figure is drawn and not which
hydrological domain it serves. It takes one value of ``FigureKind``.

.. literalinclude:: /../../hydromodpy/display/figure.py
   :start-at: FigureKind = Literal[
   :end-at: ]

``hmp config figures --kind <kind>`` filters on it.

``subject`` says what the figure draws. ``"run"`` is the default, ``"session"`` is a
calibration session and ``"runset"`` is a set of runs. ``render``, ``plot`` and
``unavailable_reason`` receive the object the subject names, which ``display/runs.py``
resolves once. A session figure asked on a run receives ``Session.of_run(run)`` and the
option ``promoted=run``, and a run that no session promoted is refused. A figure that
compares a run with a reference stays a ``"run"`` figure and takes ``reference=``.

``BaseFigure.plot`` creates the subplots with ``default_figsize``, calls ``render`` and,
when asked, saves the PNG with its provenance. ``unavailable_reason`` decides before
whether the figure applies to a run. ``[display].figures`` skips a figure that it
refuses, and ``hmp show --figure`` and ``Run.figure`` refuse it with the same sentence.
When it returns ``None``, ``render`` draws, or raises ``FigureNotApplicable`` with a
sentence for what only the data shows, such as a run with no observation. Any other
exception is a defect.

Required fields and tables
--------------------------

The registry checks these before it reads the disk.

- ``required_fields`` are the Zarr dataset names that ``Run.field(...)`` must load. A
  missing one makes the figure unavailable, and the gallery says which field is absent.
- ``optional_fields`` are read when they are there. They are turned on for a run that
  asks for the figure, but their absence does not make it unavailable. The figure then
  refuses in its own words.
- ``required_tables`` are the Parquet-backed tables (``timeseries``, ``budgets``,
  ``mass_balance``).

A need that ``spec`` cannot express (a network, a DEM raster, a lake or a piezometer)
goes into an ``unavailable_reason`` override that calls the base first and returns a
sentence. ``render`` may then assume the data is there. See
``figures/lake_abacus_comparison.py``. ``hmp config figures --run <sim_id>`` prints,
for each figure, whether the run supports it or why not.

Register
--------

The figure port has no entry-point group. The public module is the membership, and
``python -m tools.figure_table`` regenerates ``hydromodpy/display/figure_table.py``,
which the registry reads. A test regenerates it in memory and fails while the file is
stale. The table holds literals only, so answering a name, a former name or the options
of a figure loads no figure module. The general mechanism is in :doc:`plug-into-a-port`.

To rename a figure, change ``spec.name``, put the old name in ``spec.former_names`` and
regenerate the table. Project files with the old name still load, with a warning.

Once in the table, the figure is reachable from ``hmp show <sim_ref> --figure my_figure``,
``hmp export <sim_ref> --regen figures`` and the TOML below.

.. code-block:: toml

   # not checked: my_figure is the placeholder figure of this recipe
   [display]
   figures = ["piezometric_map", "water_budget", "my_figure"]

Test
----

- ``python -m tools.figure_table``, then the freshness test.
- ``tests/unit/display/test_figure_registry.py`` runs on every figure and fails when
  one accepts a run that holds nothing.
- ``tests/ports/test_figure.py`` plays every figure on the runs, the session and the
  run set of the frozen example, and fails on anything but ``FigureNotApplicable``.
- A unit test under ``tests/unit/display/`` on a synthetic ``Run`` fixture, which
  asserts a non-empty axes.

Layer boundaries
----------------

``display`` reads only ``core`` and ``results``, see :doc:`../generated/layers`. Inside
it, a shared tool never imports ``figures/``, and
``tests/unit/architecture/display_layout.yaml`` lists who may import whom. Reach the data
through ``Run`` (``run.field``, ``run.timeseries``, ``run.budget``) or a function of
``results`` that takes the run, never through raw Zarr or DuckDB calls.

See also
--------

- :doc:`../packages/display` for the figure registry.
- :doc:`add-an-exporter` if the output is a file format and not a matplotlib figure.
- :doc:`/understand/reading-results` for the user-facing figure catalog.

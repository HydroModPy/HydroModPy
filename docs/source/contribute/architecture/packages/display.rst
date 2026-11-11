Package: display
================

.. include:: ../../../../../hydromodpy/display/README.md
   :parser: myst_parser.sphinx_
   :start-line: 1

Modules
-------

.. hmp-module-table:: display

Inside the package
------------------

The package holds three things of unequal weight. The first is the figure catalogue of a
run, with the contract ``figure.py``, the registry ``figure_registry.py``, the generated
table ``figure_table.py`` and the figures of ``figures/``, one figure per file. The second is
the report engine of ``report/``, which turns blocks into static HTML pages, and
``overview/``, the data before any simulation. The third is the shared plotting tools,
``maps/`` and ``style.py``. A figure of a run, a cohort figure of a campaign summary and the
figures of ``hmp diff`` (``run_comparison.py``) all draw with these tools.

A render leaves nothing in the process. A figure is drawn on its own Agg canvas
(``new_figure`` and ``new_subplots`` in ``figure.py``), so no backend is chosen or switched
and no figure sits in the ``pyplot`` registry. The one thing matplotlib shares between
threads is ``rcParams``, so ``themed`` in ``style.py`` holds ``RENDER_LOCK`` and a
``rc_context`` for the length of one render, and ``rendering`` in ``runs.py`` does the same
for a list of figures. Two renders in two threads of one process run one after the other,
and each meets the style it asked for. ``pyplot`` is imported only by ``quicklook/viz.py``
and by the window ``[display] show`` opens, the two places a window is the point.

A user can rely on five rules. A figure shows a quantity and never tests a solver name, so
the same figure works for MODFLOW-NWT, MODFLOW 6 and Boussinesq when the run holds the field.
A figure is offered only when the run has what it needs, and a lumped run has no grid, so
every map is refused and the discharge figures stay offered. An instant is a date: a figure
that draws one instant is asked for it by ``time``, a date, ``"first"`` or ``"last"``, in
``[display] time`` or in ``[display.overrides.<figure>]``, and ``runs._resolve_time`` is the
one place a date meets a run, through ``run.periods.step_at``. The user never writes
``timestep``, and a file that writes it is refused. An option is a parameter: the keys
``[display.overrides.<figure>]`` takes are the named parameters of ``plot`` and ``render``,
read along the MRO by ``figure.option_names_of``, and a key the figure does not take is
refused at config load with the list. A figure has one name on every surface, and a renamed
figure keeps its old name in ``former_names`` so project files that use it still load with a
warning. ``difference_map``, ``side_by_side`` and ``conditioning_impact_map`` need a second
run, which ``spec`` cannot declare, so they are drawn from Python with ``reference=<run>``
and refuse with a sentence without it.

Outside the package, ``display`` imports only ``core`` and ``results``. Inside, a unit
imports only what its line of ``tests/unit/architecture/display_layout.yaml`` allows, and
``tests/unit/architecture/test_package_layouts.py`` checks every import, at module level,
inside a function or under ``TYPE_CHECKING``. The rule that matters is that no shared tool
imports ``figures/``: data a tool needs lives in the tool or in ``results``. A file of
``figures/`` whose name starts with ``_`` is a helper private to that folder, and a helper
that another part of ``display`` needs goes to ``maps/`` or ``style.py``. ``figure_registry``
answers a name from the generated table and imports no module of ``figures/``. No module
reads a ``_private`` attribute of another, which ruff rule SLF001 checks. Another package
imports only the modules of the ``public`` list of ``display_layout.yaml``, and
``calibration`` does not import ``display``.

The figures of a run flow from ``[display]`` to PNG files. ``DisplayConfig`` reads the
section and checks its names through ``figure_registry.resolve``.
``runs.render_figures_for_run`` takes each name, skips a figure whose
``unavailable_reason`` speaks and keeps the reason in the ``FigureRenderReport``, and
otherwise calls ``BaseFigure.plot``, which writes ``runs/<run>/figures/<name>.png``.
``png_metadata.stamp_png_identity`` writes the footer and the identity of the run, and the
PNG is recorded in ``runs/<run>/figures/index.json``. The figures are drawn after the seal,
so every footer carries the labelled identity of the run, or ``unlabelled`` without a seal.
``hmp export <run> --regen figures`` replays ``figures/index.json``. ``hmp show --figure``
and ``Run.figure`` go through ``runs.render_figure``, and ``hmp config figures --run``
calls ``runs.figure_availability``. A session figure asked on a promoted run receives
``Session.of_run(run)`` and the run as ``promoted``, and a subject of the wrong kind is
refused with ``NOT_PROMOTED_REASON``, ``NOT_A_RUNSET_REASON`` or ``NOT_A_RUN_REASON``.

The report of a run or a session is assembled by ``project/report.py``, the one place that
gathers the texts and the pages, because ``display`` never imports ``schema``. It hands
``display.report`` the texts and the blocks. ``report/pages.py`` builds ``Block`` objects
from a sealed run, a data overview or a calibration session, ``report/presets.py`` holds
``ReportTexts`` and the ``research`` and ``management`` presets, and ``report/engine.py``
writes ``index.html``, the review pages ``review/{compact,standard,audit,by_block}/``,
``figures/`` and ``report.json``. A figure of the preset that cannot be drawn is logged with
its reason. The engine knows no run, so the overview, the calibration session report and
the page of ``validation_cases/calibration/network_transient_b0/`` use it too. The overview
reads a ``DataOverviewState`` built by ``workflow/overview.py`` and draws one PNG per panel
switched on in ``[overview.panels]``. The cohort figures of ``hmp campaign collect`` are
drawn by ``cohort.py`` under ``summary/figures/``.

Where to add what. A map of one value per mesh face is a subclass of ``ScalarFaceMap`` on the
model of ``figures/piezometric_map.py``, with no ``render`` to write. A time series or a
chart is a ``BaseFigure`` with a ``render`` on the model of ``figures/hydrograph.py``, with
``maps.axes.style_date_axis`` for dates. A figure that lays out its own figure may define
its own ``plot``, which ``BaseFigure.__init_subclass__`` wraps so that it still takes the
common ``title`` and ``show_run_name`` options. A layer drawn on maps is a function
``draw_<name>(ax, sim, *, timestep)`` and a key of ``maps.overlays.OVERLAYS``. A panel of the
overview is a boolean of ``OverviewPanelsConfig``, its drawing function in
``overview/panels.py``, its call in ``overview/report.py`` and its line in ``PANEL_FILES``.
A block of a report page is a function of ``report/pages.py`` that returns ``Block``
objects, and the words it shows are a field of ``ReportTexts``. A read of a run that a figure
needs goes in ``results``, never in ``display``: a public method of ``Run``, capped at 50
public attributes by ``tests/unit/results/test_run_surface.py``, or else a module function
of ``results`` that takes the run. An import rule is a line of ``display_layout.yaml``. A new
figure appears in the figure catalogue of these docs at the next build, because
``tools/docs/catalogs.py`` reads ``list_figures()``.

A first reading takes ``figure.py`` for the contract, then ``figure_registry.py`` and the
generated ``figure_table.py``, then one chart, ``figures/hydrograph.py``, and one map,
``figures/piezometric_map.py``, then ``report/engine.py`` and ``report/pages.py``, and
``project/report.py`` for the texts and the call that writes a whole report.

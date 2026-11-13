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

A render leaves nothing in the process. A figure is drawn on its own Agg canvas (``new_figure``
and ``new_subplots`` in ``figure.py``), so no backend is switched and no figure sits in the
``pyplot`` registry. The one thing matplotlib shares between threads is ``rcParams``, so
``themed`` in ``style.py`` holds ``RENDER_LOCK`` and an ``rc_context`` for one render. Two
renders in two threads run one after the other, and each meets the style it asked for.
``pyplot`` is imported only by ``quicklook/viz.py`` and by the window ``[display] show`` opens.

Five rules hold for the user.

- A figure shows a quantity and never tests a solver name, so the same figure works for
  MODFLOW-NWT, MODFLOW 6 and Boussinesq when the run holds the field.
- A figure is offered only when the run has what it needs. A lumped run has no grid, so every
  map is refused and the discharge figures stay offered.
- An instant is a date. A figure is asked for it by ``time`` (a date, ``"first"`` or
  ``"last"``), and ``runs._resolve_time`` is the one place a date meets a run. A file that
  writes ``timestep`` is refused.
- An option is a parameter. The keys of ``[display.overrides.<figure>]`` are the named
  parameters of ``plot`` and ``render``, read by ``option_names_of``, and an unknown key is
  refused at config load with the list.
- A figure has one name on every surface, and a renamed figure keeps its old name in
  ``former_names`` so old project files load with a warning.

``difference_map``, ``side_by_side`` and ``conditioning_impact_map`` need a second run, which
``spec`` cannot declare. They are drawn from Python with ``reference=<run>``.

The figures of a run flow from ``[display]`` to PNG files. ``DisplayConfig`` checks the names
through ``figure_registry.resolve``. ``runs.render_figures_for_run`` takes each name, skips a
figure whose ``unavailable_reason`` speaks and keeps the reason in the ``FigureRenderReport``,
and otherwise calls ``BaseFigure.plot``, which writes ``runs/<run>/figures/<name>.png``.
``png_metadata.stamp_png_identity`` writes the footer with the identity of the run, and the PNG
is recorded in ``figures/index.json``. Figures are drawn after the seal, so a footer carries the
labelled identity of the run, or ``unlabelled`` without a seal. ``hmp export <run> --regen
figures`` replays that index. A session figure on a promoted run receives ``Session.of_run(run)``
and the run as ``promoted``, and a subject of the wrong kind is refused with
``NOT_PROMOTED_REASON``, ``NOT_A_RUNSET_REASON`` or ``NOT_A_RUN_REASON``.

``display`` never imports ``schema``, so ``project/report.py`` gathers the texts and the pages
of a report and hands ``display.report`` the texts and the ``Block`` objects. ``report/pages.py``
builds blocks from a sealed run, a data overview or a calibration session, and
``report/engine.py`` writes the HTML pages. The engine knows no run, so the overview and the
session report use it too.

The import rules are in ``tests/unit/architecture/display_layout.yaml`` and the generated
:doc:`layers page <../generated/layers>`. Outside the package, ``display`` imports only ``core``
and ``results``, and ``calibration`` does not import ``display``. Inside, no shared tool imports
``figures/``, so data a tool needs lives in the tool or in ``results``. A helper that another
part of ``display`` needs goes to ``maps/`` or ``style.py``, and ``figure_registry`` imports no
module of ``figures/``.

Where to add what. A map of one value per mesh face is a subclass of ``ScalarFaceMap``, as in
``figures/piezometric_map.py``. A time series or a chart is a ``BaseFigure`` with a ``render``,
as in ``figures/hydrograph.py``. A layer drawn on maps is a function ``draw_<name>`` and a key of
``maps.overlays.OVERLAYS``. A panel of the overview is a boolean of ``OverviewPanelsConfig``, its
drawing function in ``overview/panels.py`` and its line in ``PANEL_FILES``. A block of a report
page is a function of ``report/pages.py``, and its words are a field of ``ReportTexts``. A read
of a run that a figure needs goes in ``results``, never in ``display``. A new figure appears in
the generated figure list at the next build.

The request path draws a figure from the name of a variable. ``request.py`` holds the request and
its checks and imports no plotting library. ``subject.py`` is the only module that reads a run,
``variables.py`` converts to the display unit, and a frame of ``frames/`` has a ``data`` that returns
a table and a ``draw`` that puts it on one axes. ``render.py`` draws the overlays of ``overlays.py``
after the frame, and ``output.py`` writes the files and the ledger entry that
``hmp export --regen figures`` replays. The frames are ``map``, ``series``, ``section``, ``xy``,
``distribution``, ``groups`` and ``table``, and ``table`` stays flagged not ready until the column
registry exists. A frame lists the panel fields it reads in ``FIELDS`` and refuses the others by
name through ``subject.refuse_fields``, so a new panel field cannot be ignored without a test
failing. The colour norm and the colours of a budget term are written once in ``variables.py``,
the scores of a run and the area of a zone once in ``frames/series.py``. A new frame is a module of
``frames/`` named as its key of ``request.FRAMES``, and a new context layer is a key of ``request.OVERLAY_FIELDS`` with the
function of the same name in ``overlays.py``.

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
and ``new_subplots`` in ``static.py``), so no backend is switched, no figure sits in the
``pyplot`` registry and no ``rcParams`` is written. The ``Theme`` of ``theme.py`` carries the
colours, the fonts and the dpi of one render, so two renders in two threads meet the style each
asked for. ``pyplot`` is imported only by ``quicklook/viz.py`` and by the window ``[display] show``
opens.

Four rules hold for the user.

- A figure shows a quantity and never tests a solver name, so the same figure works for
  MODFLOW-NWT, MODFLOW 6 and Boussinesq when the run holds the field.
- A figure is refused with a sentence when the run lacks what it needs. A lumped run has no grid,
  so every map is refused and the discharge figures stay drawn.
- An instant is a date. A figure is asked for it by ``time`` (a date, ``"first"`` or
  ``"last"``), and a file that writes ``timestep`` is refused.
- A figure has one name on every surface. A name of a pre-release figure is refused with the
  request that replaces it, from ``retired_figures.toml``.

``display`` never imports ``schema``, so ``project/report.py`` gathers the texts and the pages
of a report and hands ``display.report`` the texts and the ``Block`` objects. ``report/pages.py``
builds blocks from a sealed run, a data overview or a calibration session, and
``report/engine.py`` writes the HTML pages. The engine knows no run, so the overview and the
session report use it too.

The import rules are in ``tests/unit/architecture/display_layout.yaml`` and the generated
:doc:`layers page <../generated/layers>`. Outside the package, ``display`` imports only ``core``
and ``results``, and ``calibration`` does not import ``display``. Inside, only ``render.py`` names
a frame or a special figure as text, by its key in ``request.FRAMES`` or ``request.SPECIALS``.
A read of a run that a figure needs goes in ``results``, never in ``display``. A panel of the
overview is a boolean of ``OverviewPanelsConfig``, its drawing function in ``overview/panels.py``
and its line in ``PANEL_FILES``. A block of a report page is a function of ``report/pages.py``,
and its words are a field of ``ReportTexts``.

The request path draws a figure from the name of a variable. ``request.py`` holds the request and
its checks and imports no plotting library. ``subject.py`` is the only module that reads a run,
``variables.py`` converts to the display unit, and a frame of ``frames/`` has a ``data`` that returns
a table and a ``draw`` that puts it on one axes. ``render.py`` draws the overlays of ``overlays.py``
after the frame, and ``output.py`` writes the files and the ledger entry that
``hmp export --regen figures`` replays. The frames are ``map``, ``series``, ``section``, ``xy``,
``distribution``, ``groups``, ``table`` and ``volume``. The interactive engine of ``interactive.py`` draws ``map``, ``series`` and ``volume`` as plotly figures of up to 100 000 cells, and ``output.py`` writes them as HTML. Plotly is imported only when such a figure is drawn. A table column is a name of ``COLUMN_REGISTRY``, and a
session is drawn by ``series``, ``xy`` and ``distribution`` from its ``trials.<column>`` names. A
map panel that gives a run name to ``against`` subtracts that run, which ``render`` receives
resolved. A frame lists the panel fields it reads in ``FIELDS`` and refuses the others by
name through ``subject.refuse_fields``, so a new panel field cannot be ignored without a test
failing. The colour norm and the colours of a budget term are written once in ``variables.py``,
the scores of a run and the area of a zone once in ``frames/series.py``. A new frame is a module of
``frames/`` named as its key of ``request.FRAMES``, and a new context layer is a key of ``request.OVERLAY_FIELDS`` with the
function of the same name in ``overlays.py``.

A special figure is a function ``draw(subject, ax, theme)`` that draws one axes for a case no frame
expresses, such as a fit, a matching of two networks or the trace of a root search. It lives in a
module of ``special/`` that also holds ``SUBJECT`` (``run``, ``session`` or ``runset``) and may
hold ``WIDTH``. The function may take the keywords ``station`` and ``time``, and without them it
reads the station the run scored. ``presets.py`` lists the modules, so each one is a preset named as
its module, and ``render`` refuses a subject of another kind, except a run given to a session figure,
which stands for the session that promoted it. ``special/records.py`` holds the reads that several of
them share and draws nothing. The list is closed at twelve, and a thirteenth figure is a frame, a
variable or a preset first.

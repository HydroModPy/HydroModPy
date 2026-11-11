Add a block to the HTML report
==============================

Use this recipe to add a block to a report page, or to change which figures a
preset shows. A report is a static HTML page built from blocks. A block holds
metrics, tables, pictures, links and prose.

The engine lives in ``hydromodpy.display.report``. It has three modules.

- ``engine.py`` holds the frozen dataclasses and ``write_pages``. It writes the
  HTML shell, the anchors, the level navigation and the per-block level
  switches. It copies the figures and frames a missing required figure.
- ``pages.py`` builds blocks and nothing else (``run_blocks``, ``sheet_blocks``,
  ``overview_blocks``, ``session_blocks``, ``draw_named_figures``).
- ``presets.py`` holds ``ReportTexts`` and ``PRESETS``.

``hydromodpy/project/report.py`` (``report_run`` and ``report_session``) is the
one place that assembles the texts and the pages. ``hydromodpy.display`` never
imports the schema, so the texts reach it as a ``ReportTexts`` value.

Where to document it
--------------------

- The descriptions of the keys and the help of ``hmp report`` say when a report
  is produced, its output paths and how to read it. The reference pages are
  generated from them. Example: :doc:`/reference/cli/report`.
- This page is the contributor recipe.
- :doc:`/contribute/architecture/packages/display` summarizes the ownership.

Audits and working notes stay out of the repository.

The items of a block
--------------------

.. code-block:: python

   from hydromodpy.display.report.engine import (
       Block,
       Link,
       Metric,
       Picture,
       Prose,
       Table,
       pairs_table,
   )

   block = Block(
       "run_identity",
       "Run identity",
       "Short human-readable context.",
       min_level="compact",
       items=(
           ("compact", Metric("Sites", 6)),
           ("standard", Metric("Failed runs", 0)),
           ("standard", Picture("catchment_map", "Map", map_path, required=True)),
           ("audit", pairs_table("strategy", "Strategy", (("Profile", "gauged"),))),
           ("audit", Link("manifest", manifest_path, "manifest")),
       ),
   )

The levels are ``compact``, ``standard`` and ``audit``, in that order, and
``LEVELS`` lists them. Each item carries the first level that shows it, and a
page at a higher level shows it too. ``min_level`` is the first level that
shows the block at all. ``compact`` should be enough to decide whether the run
looks plausible, ``standard`` explains the main interpretation, and ``audit``
exposes provenance, detailed tables and links.

``Picture`` takes a path, or ``None`` when the file does not exist. With
``required=True`` a missing file is shown as "Required figure missing" and is
listed under ``missing`` in ``report.json``. With ``required=False`` it just
does not appear.

Add a block
-----------

A block is a function of a ``Run`` in ``pages.py``. Add it to the list that
``run_blocks`` returns, or to ``sheet_blocks``, ``overview_blocks`` or
``session_blocks`` for the other pages. Read the sealed run, never the solver
folder. A block holds no HTML, only items. Text the reader sees in a sentence
is not written there: it comes from ``ReportTexts``, which ``project/report.py``
fills from the phrase table.

Keep the ``id`` stable. It drives the anchors, the table of contents and the
local-storage key of the per-block level selector.

Name a figure in a preset
-------------------------

``PRESETS`` maps a preset name to a ``Preset``. Its ``figures`` field names the
run figures by level, and its ``panels`` field names the overview panels that
fill the context blocks.

.. code-block:: python

   "research": Preset(
       name="research",
       levels=True,
       figures={"compact": ("watershed_id_card",), "standard": ("water_budget",), "audit": ()},
       panels=("map_dem",),
   )

A name must be a registered figure (see :doc:`add-a-figure`). ``run_blocks``
turns each name into a required ``Picture`` at its level. The same names are
drawn by ``draw_named_figures`` after the seal, so a figure named here appears
in ``figures/`` of the run and on the page. The ``research`` preset writes three
levels. The ``management`` preset writes one page, ``levels=False``.

Output layout
-------------

``write_pages`` writes under the folder it is given, ``runs/<run>/report/`` for
a run and ``sessions/<s>/report/`` for a session.

- ``index.html`` is the standard page.
- ``review/compact/``, ``review/standard/``, ``review/audit/`` and
  ``review/by_block/``, each with an ``index.html``, when ``levels=True``.
  ``by_block`` lets each block choose its own level.
- ``sheet-<lang>/index.html`` is the one page of the management preset, in
  ``en`` or ``fr``.
- ``figures/`` holds the copied pictures.
- ``report.json`` (schema ``hydromodpy.report.v1``) lists the preset, the
  language, the label, the render date and each figure with its title, its file
  or null, and whether it was required, plus ``missing`` and ``copied``, the
  files the engine copied under ``figures/``. A new render removes only those.

The generated HTML is not a source of truth. The sealed run and the figure
code are. The report is not in the seal inventory and can be written again with
``hmp report catchment`` or ``hmp report render``.

Documentation illustrations
---------------------------

Generate an illustration from a small versioned source. Commit the reviewed
image under ``docs/source/_static/`` and name in the page the command that
produced it. Do not make the docs build run a solver, a provider or a long job.
Avoid an image whose only source is a local browser screenshot.

Tests to add
------------

- Engine tests under ``tests/unit/display/report`` for escaping, anchors,
  missing figures, links, levels and ``report.json``.
- A test of the new block on a small sealed run, for its ids and its items at
  each level.

Pitfalls
--------

- Do not write a large HTML template when a ``Block`` can express the content.
- Do not put business rules in ``engine.py``. A block reads the run in
  ``pages.py``.
- Do not import the schema from ``display``. Pass what is needed through
  ``ReportTexts`` from ``project/report.py``.
- Mark an optional picture ``required=False``, so that a figure the run could
  not draw does not look like a failure.
- Keep generated HTML and copied figures out of version control.

See also
--------

- :doc:`../packages/display` for the ownership of ``display/report``.
- :doc:`/reference/cli/report` for the user-facing reports.

Add a block to the HTML report
==============================

Use this recipe to add a block to a report page, or to change which figures a preset
shows. A report is a static HTML page built from blocks. A block holds metrics, tables,
pictures, links and prose.

The engine lives in ``hydromodpy.display.report``, in three modules.

- ``engine.py`` holds the frozen dataclasses and ``write_pages``. It writes the HTML
  shell, the anchors, the level navigation and the per-block level switches. It copies
  the figures and frames a missing required figure.
- ``pages.py`` builds blocks and nothing else (``run_blocks``, ``sheet_blocks``,
  ``overview_blocks``, ``session_blocks``, ``draw_named_figures``).
- ``presets.py`` holds ``ReportTexts`` and ``PRESETS``.

``hydromodpy/project/report.py`` (``report_run`` and ``report_session``) is the one place
that assembles the texts and the pages. ``display`` never imports the schema, so the
texts reach it as a ``ReportTexts`` value. The help of ``hmp show --report`` says when a report is produced and how to read it.

Files to edit
-------------

A block is a function of a ``Run`` in ``pages.py``. Add it to the list that
``run_blocks`` returns, or to ``sheet_blocks``, ``overview_blocks`` or ``session_blocks``
for the other pages. Read the sealed run, never the solver folder. A block holds no
HTML, only items. A sentence the reader sees comes from ``ReportTexts``, which
``project/report.py`` fills from the phrase table. Keep the ``id`` stable, because it
drives the anchors, the table of contents and the local-storage key of the per-block
level selector.

Contract
--------

A block is a titled group of items, each with the first level that shows it.

.. literalinclude:: /../../hydromodpy/display/report/engine.py
   :pyobject: Block

The items are ``Metric``, ``Picture``, ``Table``, ``Link`` and ``Prose``, and
``pairs_table`` builds a two-column table.

.. code-block:: python

   block = Block(
       "run_identity",
       "Run identity",
       "Short human-readable context.",
       min_level="compact",
       items=(
           ("compact", Metric("Sites", 6)),
           ("standard", Picture("catchment_map", "Map", map_path, required=True)),
           ("audit", pairs_table("strategy", "Strategy", (("Profile", "gauged"),))),
           ("audit", Link("manifest", manifest_path, "manifest")),
       ),
   )

The levels are ``compact``, ``standard`` and ``audit``, in that order, and a page at a
higher level shows the items of the lower ones too. ``compact`` should be enough to
decide whether the run looks plausible. ``standard`` explains the main interpretation,
and ``audit`` exposes provenance, detailed tables and links.

``Picture`` takes a path, or ``None`` when the file does not exist. With
``required=True`` a missing file shows as "Required figure missing" and is listed under
``missing`` in ``report.json``. Mark a picture ``required=False`` when the run may not
be able to draw it, so that it does not look like a failure.

Name a figure in a preset
-------------------------

``PRESETS`` maps a preset name to a ``Preset``. Its ``figures`` field names the run
figures by level, and its ``panels`` field names the overview panels that fill the
context blocks.

.. literalinclude:: /../../hydromodpy/display/report/presets.py
   :pyobject: Preset

A name must be a registered figure, see :doc:`add-a-figure`. ``run_blocks`` turns each
name into a required ``Picture`` at its level. ``draw_named_figures`` draws the same
names after the seal, so a figure named here appears in ``figures/`` of the run and on
the page. The ``research`` preset writes three levels, and ``management`` writes one
page with ``levels=False``.

Output
------

``write_pages`` writes under ``runs/<run>/report/`` for a run and
``sessions/<s>/report/`` for a session. ``index.html`` is the standard page. With
``levels=True`` it also writes ``review/compact/``, ``review/standard/``,
``review/audit/`` and ``review/by_block/``, where each block chooses its own level. The
management preset writes ``sheet-<lang>/index.html``. ``report.json`` (schema
``hydromodpy.report.v1``) lists the preset, the language, each figure with its file and
whether it was required, and ``missing`` and ``copied``. A new render removes only the
files listed in ``copied``.

The report is not in the seal inventory, and ``hmp show RUN --report`` writes it again.
Keep generated HTML and copied figures out of version control.

A documentation illustration is a reviewed image under ``docs/source/_static/``, and
the page names the command that produced it.

Test
----

- Engine tests under ``tests/unit/display/report`` for escaping, anchors, missing
  figures, links, levels and ``report.json``.
- A test of the new block on a small sealed run, for its ids and its items at each
  level.

Layer boundaries
----------------

Business rules stay out of ``engine.py``. ``display`` reads only ``core`` and ``results``, see
:doc:`../generated/layers`, so anything from the schema goes through ``ReportTexts``.

See also
--------

- :doc:`../packages/display` for the ownership of ``display/report``.
- :doc:`/reference/cli/show` for the user-facing reports.

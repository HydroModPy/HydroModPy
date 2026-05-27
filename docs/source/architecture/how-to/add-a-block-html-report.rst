Add a Block HTML Report
=======================

Use this recipe when a workflow must emit a static HTML report composed of
reusable blocks: metrics, figures, tables, artifact links, and warnings.

The shared renderer lives in ``hydromodpy.display.report_blocks``. Workflow
code owns the scientific content; the shared renderer owns the HTML shell,
anchors, level navigation, per-block level switches, relative artifact links,
and missing-figure placeholders.

Where to Document It
--------------------

There are three useful places for report documentation. Keep them separate:

- **User guide or workflow page**: describe when the report is produced, the
  stable output paths, and how users should read it. Example:
  ``user_guide/workflows/site_selection.rst``.
- **Developer recipe**: describe how to add or migrate a report producer. This
  page is the canonical contributor recipe.
- **Package reference**: summarize ownership and reading paths in
  ``architecture/packages/display.rst`` and, when the report belongs to the
  higher-level reporting layer, ``architecture/packages/reporting.rst``.

``docs/_dev_notes`` is for audits, migration logs, and temporary working
notes. It is not the source of truth for RTD-facing user or developer
documentation.

Contract
--------

A block report is built from immutable dataclasses:

.. code-block:: python

   from hydromodpy.display.report_blocks import (
       ReportBlock,
       ReportFigure,
       ReportLink,
       ReportMetric,
       ReportTable,
       key_value_table,
       write_report_page,
       write_report_page_with_block_variants,
   )

   block = ReportBlock(
       block_id="selection_identity",
       title="Selection identity",
       level="compact",
       lead="Short human-readable context.",
       metrics=(
           ReportMetric("Selected sites", 6),
           ReportMetric("Rejected sites", 0),
       ),
       figures=(
           ReportFigure(
               "site_selection_map",
               "Review map",
               map_path,
               "DEM background, basins, outlets, and observation stations.",
               embed=True,
           ),
       ),
       tables=(
           key_value_table(
               "strategy",
               "Strategy",
               (("Profile", "gauged_downstream_station"),),
           ),
       ),
       links=(ReportLink("manifest", manifest_path, "manifest"),),
   )

The stable detail levels are ``compact``, ``standard``, and ``audit``.
``compact`` should be enough to decide whether the run looks plausible,
``standard`` should explain the main scientific interpretation, and ``audit``
should expose provenance, detailed tables, hashes, and artifact links.

Files to Create or Edit
-----------------------

A typical workflow report has two workflow-owned modules:

.. code-block:: text

   hydromodpy/<domain>/<workflow>/reports/blocks.py
   hydromodpy/<domain>/<workflow>/reports/html.py

``blocks.py`` converts validated manifests or run artifacts into
``ReportBlock`` instances. It contains workflow knowledge, but no low-level
HTML.

``html.py`` resolves paths, validates required artifacts, calls the block
builder, and writes the HTML files.

For a simple single-level report:

.. code-block:: python

   def render_my_report(manifest_path: Path, output_path: Path) -> Path:
       manifest = load_manifest(manifest_path)
       blocks = build_my_report_blocks(manifest, manifest_path=manifest_path)
       return write_report_page(
           output_path=output_path,
           title=str(manifest["run_id"]),
           subtitle="Static review report.",
           blocks=blocks,
       )

For global levels plus a per-block switch page:

.. code-block:: python

   DETAIL_LEVELS = ("compact", "standard", "audit")


   def _level_links(destination: Path) -> dict[str, Path]:
       return {
           "compact": destination.parent / "compact" / destination.name,
           "standard": destination.parent / "standard" / destination.name,
           "audit": destination.parent / "audit" / destination.name,
           "by_block": destination,
       }


   def render_my_report(manifest_path: Path, output_path: Path) -> Path:
       manifest = load_manifest(manifest_path)
       blocks = build_my_report_blocks(manifest, manifest_path=manifest_path)
       variants = build_my_report_block_variants(blocks)
       links = _level_links(output_path)

       for level in DETAIL_LEVELS:
           write_report_page(
               output_path=links[level],
               title=str(manifest["run_id"]),
               subtitle=f"{level} view",
               blocks=blocks_for_detail_level(blocks, level),
               current_level=level,
               level_links=links,
           )

       return write_report_page_with_block_variants(
           output_path=output_path,
           title=str(manifest["run_id"]),
           subtitle="Per-block detail view",
           block_variants=variants,
           current_level="by_block",
           default_level="standard",
           level_links=links,
       )

Output Layout
-------------

Keep one stable user-facing entry point, then add optional level pages around
it. Existing reports use these patterns:

- ``review/index.html`` for site-selection review reports;
- ``review/compact/index.html``, ``review/standard/index.html`` and
  ``review/audit/index.html`` for global detail levels;
- ``web/index.html`` for the catchment report's standard page;
- ``web_review/by_block/index.html`` for a catchment report page where each
  block can choose its own detail level.

Do not make generated HTML the source of truth. The source of truth is the
manifest, TOML, run catalog, and regenerated figure artifacts.

Updateable Documentation Illustrations
--------------------------------------

Documentation illustrations for block reports should be generated from a
small, versioned source rather than edited by hand. The goal is that a layout
or contract change can be refreshed by one command and checked in CI.

Use this decision rule:

- **Static workflow examples**: prefer ``tools/doc_gallery``. Add a small
  gallery case whose source files are committed, then regenerate with
  ``python -m tools.doc_gallery --only <slug>`` and verify with
  ``python -m tools.doc_gallery --check --only <slug>``. This is the right
  home for screenshots or exported PNGs shown in user pages.
- **Lightweight inventories or diagrams derived from Python constants**:
  prefer a generator under ``tools/doc_figures`` or a similar small tool wired
  into the Sphinx ``builder-inited`` hook. This is appropriate for RST
  fragments, tables, or diagrams that can be rebuilt without solvers or
  network access.
- **Heavy solver or provider examples**: generate artifacts explicitly before
  the docs build, commit the reviewed outputs, and keep Sphinx as a reader
  only. Do not make RTD execute hydrological providers, MODFLOW binaries, PETSc
  jobs, or long site-selection campaigns just to draw one illustration.

For ``site_selection``, the minimum updateable illustration should come from a
short fixture or example that writes ``review/site_selection_map.png`` and the
four HTML pages under ``review/``. The documentation page can then reference
the committed PNG or a small derived screenshot, while the manifest and source
TOML remain the traceable inputs.

For ``catchment_report``, the minimum updateable illustration should come from
a tiny report fixture or one short basin example that writes
``web/index.html``, ``web_review/by_block/index.html`` and
``block_report_postflight.json``. Keep the screenshot or mosaic under
``docs/source/_static/`` only if it can be regenerated from the fixture.

Avoid images whose only source is a local browser screenshot. If a screenshot
is needed, keep a script or gallery case that rebuilds the report, opens the
stable HTML entry point, captures the viewport, and writes the committed image.
The committed image is then a build artifact, not a hand-maintained source.

Tests to Add
------------

Add focused tests at two levels:

- renderer tests under ``tests/unit/display`` for escaping, anchors, missing
  figures, links, and per-block level controls;
- workflow tests next to the report producer for manifest loading, output path
  stability, expected block IDs, and generated file existence.

When the report consumes a figure inventory, add a small postflight or contract
test that fails when required figures are missing or stale links are emitted.

Pitfalls
--------

- Do not build large workflow-specific HTML templates when ``ReportBlock`` can
  express the content.
- Do not put business rules in ``hydromodpy.display.report_blocks``. Keep them
  in the workflow-specific ``blocks.py`` module.
- Mark optional figures as ``required=False``. Required missing figures are
  rendered as placeholders instead of disappearing silently.
- Keep ``block_id`` stable. It drives anchors, table of contents entries, and
  local-storage keys for the per-block level selector.
- Keep generated HTML and copied figures out of version control unless a test
  fixture deliberately needs a tiny frozen artifact.

See Also
--------

- :doc:`../packages/display` for ownership of ``display/report_blocks``.
- :doc:`/user_guide/catchment-report` for the user-facing catchment report
  contract.
- :doc:`/user_guide/workflows/site_selection` for the site-selection HTML
  output contract.

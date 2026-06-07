# Site-selection reporting

This package renders static review material from a completed
`site_selection` run.

The reporting layer does not run provider access, build candidates, delineate
catchments, score criteria, or write the official selection manifest. Its input
contract is `site_selection_manifest.json` plus the artifacts declared by that
manifest.

## Runtime flow

1. `hydromodpy.workflow.site_selection` or the spatial build writes
   `site_selection_manifest.json`.
2. `render_site_selection_html_report()` validates the manifest and resolves
   artifact paths through `hydromodpy.schema.site_selection_manifest`.
3. `figures.py` renders the static map artifact.
4. `blocks.py` converts selected sites, rejected sites, criteria components,
   evidence, and candidate audit rows into report blocks.
5. `html.py` writes `review/index.html` plus the fixed
   `compact`, `standard`, and `audit` views.

## Files

- `html.py`: entry point for rendering static HTML from a manifest.
- `blocks.py`: report-block construction and detail-level variants.
- `figures.py`: static map rendering from manifest-declared spatial artifacts.
- `plan.py`: dry-run and planning report helpers.

## Invariants

- The manifest is the hand-off contract.
- Missing optional artifacts should degrade the report rather than rerun the
  workflow.
- Report blocks should consume normalized CSV, JSONL, GeoJSON, or manifest
  content, not provider-specific payloads.
- The HTML output is optional and reproducible from the manifest.
- New report sections should be added as blocks before changing the page
  renderer.

## Related documentation

- User workflow page: `docs/source/user_guide/workflows/site_selection.rst`
- Developer architecture: `docs/source/architecture/site_selection/`
- Spatial package README: `hydromodpy/spatial/site_selection/README.md`

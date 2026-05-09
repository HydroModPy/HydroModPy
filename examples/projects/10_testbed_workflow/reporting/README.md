# Generic Testbed Web Reporting

This directory contains a reusable HTML post-processor for workflow outputs
created by the existing testbed and regional-lab contracts.

The generator does not create meshes, run simulations, compute scientific
metrics, or add an alternate execution path. It reads artifacts already written
by the standard workflows:

- `testbed_manifest.json`, `testbed_cases.csv`, `testbed_metrics.csv`,
  `testbed_report.md`, and generated child TOML files;
- or `regional_lab_report.json`, `regional_lab_site_inventory.csv`,
  `regional_lab_case_matrix.csv`, and `regional_lab_execution_metrics.csv`.

## Usage

```powershell
python examples\projects\10_testbed_workflow\reporting\generate_testbed_web_report.py `
  examples\projects\10_testbed_workflow\outputs\nwt_small_catchment_flux `
  --site-catalog examples\projects\10_testbed_workflow\site_tables\armorican_demo_sites.csv `
  --title "Generic NWT flux testbed report"
```

By default the HTML is written under:

```text
<output_root>/web_synthesis/index.html
<output_root>/web_synthesis/cases/<case_id>.html
```

Use `--web-dir web` only when the output directory does not already contain a
specialized report at `web/index.html`.

Optional provenance links can be added when the site catalog was created by an
upstream scan workflow:

```powershell
python examples\projects\10_testbed_workflow\reporting\generate_testbed_web_report.py `
  <output_root> `
  --site-catalog <site_catalog.csv> `
  --site-generation-config <catchment_scan_config.toml> `
  --site-generation-summary <catchment_scan_summary.json>
```

When these optional files are supplied, the synthesis page displays the main
site-generation parameters and any available JSON/CSV counters in addition to
the source links.

Comparison reports are auto-discovered when they are stored under:

```text
<output_root>/comparisons/<comparison_id>/
  comparison_manifest.json
  comparison_metrics.csv
  comparison_figures/
  web/index.html
```

External comparison folders can also be passed explicitly:

```powershell
python examples\projects\10_testbed_workflow\reporting\generate_testbed_web_report.py `
  <output_root> `
  --comparison-root <comparison_output_root>
```

The campaign page lists all discovered comparisons. A case page embeds the key
comparison figures when the comparison identifier or folder path contains the
case/site identifier, for example `site_01_mf6_vs_bouss`.

## Current Scope

Implemented pages:

- campaign synthesis for `workflow = "testbed"`;
- case pages for each testbed variant;
- comparison summary and key comparison figures when comparison reports exist;
- regional-lab synthesis for `workflow = "regional_lab"`;
- site pages for regional-lab inventories.

The campaign synthesis keeps metrics compact on purpose: it reports row counts,
status counts, populated metric columns, and a direct link to the full
`testbed_metrics.csv`. Per-case simulation HTML pages are linked explicitly
when the output root already contains pages such as `web/site_01.html`.

Reserved but not implemented yet:

- method-centered pages under `methods/`;
- process-centered pages under `processes/`;
- comparison pages, which should remain produced by the existing comparison
  workflow and be linked from the synthesis page.

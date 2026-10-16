# `hydromodpy/reporting`

Standalone HTML pages that put several results side by side. A calibration
session becomes one page with its convergence figures and its best fit. A
comparison of sealed runs (`hmp report compare`) becomes a browsable report. A
site selection becomes a review page. Figures come from `display`, derived series from `analysis`,
data from `results`; this package composes them and writes the page.
This file is the map of the package: what each part answers, the import
rules, who calls it, and where to add what.

## Parts

| part | answers |
|---|---|
| `calibration_report.py` | the HTML report of one calibration session: `render_session` takes a payload shaped like `SessionReportPayload` (built by `calibration.report.load_session_report_data`), renders the six `calibration_*` figures from the `display` registry and a best-fit panel, and writes `sessions/<session>/report/index.html`, the figures under `sessions/<session>/figures/` |
| `comparison/compare.py` | `hmp report compare`: `compare_runs` resolves the references to sealed runs, groups them (one group, or one per site under `--by site`), runs `analysis.comparison.run_comparison` per group and renders each page under `summary/report/compare/<refs>/` of the project, or `--out` |
| `comparison/render.py` | the web report of one comparison folder: `write_comparison_web_report` |
| `comparison/context.py` | what the page reads: `comparison_manifest.json` (with its `case_check` block), the metric and budget tables, the figure list; and the domain head profile figures it draws from the runs' `fields.zarr` |
| `comparison/figures.py`, `comparison/html_utils.py` | how the figures are grouped into categories, and small HTML helpers |
| `comparison/sections/` | one function per section of the page, their templates, and the loaders of config payloads |
| `site_selection/` | the review reports of a site selection: `html.py` (the report of a manifest, `render_site_selection_html_report`), `plan.py` (the report of a plan manifest), `blocks.py` and `figures.py` (the blocks and the map they use) |

## Import rules

`layer_matrix.yaml` gives reporting `core`, `schema`, `config`, `results`,
`display`, `analysis` and itself. Today it imports `core`, `schema`,
`results`, `display` and `analysis`; it imports no `config`. Four rules:

1. `display` never imports `reporting`. The page structure that several
   reports share lives in `display/report_blocks`; `site_selection/` renders
   through it.
2. `analysis` never imports `reporting`. The comparison is computed in
   `analysis/comparison` and its page is rendered here, from
   `comparison/compare.py`.
3. `reporting -> analysis` is allowed: `comparison/compare.py` runs the
   comparison, `comparison/context.py` reads the manifest and redraws the head
   profile series from the runs.
4. `calibration` does not import `reporting`. The calibration session report
   is rendered by `step_render_calibration_report` in
   `workflow/steps/calibration.py`, which reads the session with
   `calibration.report` and hands it to `render_session`.

No `reporting_layout.yaml` orders the parts inside the package.

Who imports reporting: `workflow` (the calibration step) and `cli`
(`hmp report compare`; `hmp site select` hands the site-selection renderers to
`spatial/site_selection/runner.py`, which never imports reporting).

## Tree

```
hydromodpy/reporting/
  calibration_report.py
  comparison/       compare.py  render.py  context.py  figures.py  html_utils.py
    sections/       sections.py  templates.py  io.py
  site_selection/   html.py  plan.py  blocks.py  figures.py
```

## Where a report is written

| report | default output |
|---|---|
| calibration session | `sessions/<session>/report/index.html`, figures in `sessions/<session>/figures/` |
| comparison | `<project>/summary/report/compare/<refs>/[<site>/]web/index.html`, or under `--out` |
| site selection | `<output_root>/review/index.html` of the manifest |
| site-selection plan | `<output_root>/review/index.html` of the plan manifest |

Nothing a report writes is a source of truth. A report is regenerated from
the runs, the sessions and the manifests it reads.

## Where to add what

| to add | where |
|---|---|
| a figure in the calibration report | a registered `calibration_*` figure in `display/figures/`, its name in `_DEFAULT_FIGURE_NAMES` of `calibration_report.py` |
| a section of the comparison page | a function in `comparison/sections/sections.py` and its entry in `default_sections()` |
| a report of another workflow | a package or module in `reporting/` built on `display/report_blocks`, called from the workflow; see `docs/source/contribute/architecture/how-to/add-a-block-html-report.rst` |
| a datum the comparison page reads | `comparison/context.py` (`ComparisonWebContext`), with the file written by `analysis/comparison/run_comparison.py` |

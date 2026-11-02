# `hydromodpy/reporting`

Standalone HTML page that puts the results of a calibration session side by side,
with its convergence figures and its best fit. Figures come from `display`, derived
data from `results`; this package composes them and writes the page. This file is
the map of the package: what it answers, the import rules, who calls it, and where
to add what.

## Parts

| part | answers |
|---|---|
| `calibration_report.py` | the HTML report of one calibration session: `render_session` takes a payload shaped like `SessionReportPayload` (built by `calibration.report.load_session_report_data`), renders the six `calibration_*` figures from the `display` registry and a best-fit panel, and writes `sessions/<session>/report/index.html`, the figures under `sessions/<session>/figures/` |

## Import rules

`layer_matrix.yaml` gives reporting `core`, `schema`, `config`, `results`,
`display`, `analysis` and itself. Two rules:

1. `display` never imports `reporting`. The page structure that several
   reports share lives in `display/report_blocks`.
2. `calibration` does not import `reporting`. The calibration session report
   is rendered by `step_render_calibration_report` in
   `workflow/steps/calibration.py`, which reads the session with
   `calibration.report` and hands it to `render_session`.

No `reporting_layout.yaml` orders the parts inside the package.

Who imports reporting: `workflow` (the calibration step) and `cli`
(`hmp report render`).

## Tree

```
hydromodpy/reporting/
  calibration_report.py
```

## Where a report is written

| report | default output |
|---|---|
| calibration session | `sessions/<session>/report/index.html`, figures in `sessions/<session>/figures/` |

Nothing a report writes is a source of truth. A report is regenerated from
the runs, the sessions and the manifests it reads.

## Where to add what

| to add | where |
|---|---|
| a figure in the calibration report | a registered `calibration_*` figure in `display/figures/`, its name in `_DEFAULT_FIGURE_NAMES` of `calibration_report.py` |
| a report of another workflow | a package or module in `reporting/` built on `display/report_blocks`, called from the workflow; see `docs/source/contribute/architecture/how-to/add-a-block-html-report.rst` |

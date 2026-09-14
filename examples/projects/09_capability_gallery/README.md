# 09 - Capability gallery

Versioned source assets for the documentation capability gallery: PNG
figures, JSON manifests and metric summaries, checked in so a Sphinx build
never reruns MODFLOW 6, MODFLOW-NWT, PETSc or Boussinesq. Four categories:
geographic overviews of the Nancon watershed (EPSG:2154), MODFLOW 6/Boussinesq
comparisons on natural-geology test sites, MODFLOW 6/Gmsh/GWT simulation
regressions, and cross-code surface-interaction benchmarks.

## Run

There is no single command for this example. Each category is refreshed from
its own producing workflow, then republished here.

```bash
# a launcher TOML with [analysis.capability_gallery] enabled republishes its
# selected figures and manifest.json under simulation_regression/<case>/
hmp run <launcher>.toml

# code-comparison PNGs and JSON, rebuilt from committed solver runs under out/
python tools/doc_gallery/generate_code_comparison_assets.py

# one simulation-comparison bundle, copied from a testbed output root
python -m tools.doc_gallery.import_simulation_comparison \
  examples/projects/10_testbed_workflow/outputs/<campaign>/comparisons/<comparison_id> \
  --slug <slug> --title "Readable Case Title" --study-area "..."

# rebuild the gallery pages from committed artifacts, no solver involved
python -m tools.doc_gallery --only <slug>
python -m tools.doc_gallery --check --only <slug>
```

`python -m tools.doc_gallery --help` answers in well under a second. The
producing workflows (MODFLOW 6, MODFLOW-NWT, PETSc, Boussinesq runs) are the
expensive part and are not timed here.

## Layout

| Directory | Content |
|---|---|
| `geographic/` | watershed overview, BD Topage hydrography overlay, Nancon identity card and observed-timeseries figures |
| `simulation_regression/` | committed figures and `manifest.json` from MODFLOW 6/Gmsh/GWT and MODFLOW 6/NWT transient launcher runs |
| `simulation_comparison/` | `case.json`, `comparison_manifest.json` and `summary_metrics.csv` for two natural-geology MF6/Boussinesq comparisons |
| `code_comparison/` | PNG/JSON pairs for two cross-code surface-interaction benchmarks (no-seepage and recharge-ramp) |

## What it shows

`python -m tools.doc_gallery` is the only reader of this tree at doc-build
time: it discovers every `case.json` and manifest here and renders the RST
pages under `docs/source/capability_gallery/`. Nothing in that build touches
a solver, which keeps the documentation reproducible without MODFLOW, PETSc
or a WSL/Linux toolchain installed.

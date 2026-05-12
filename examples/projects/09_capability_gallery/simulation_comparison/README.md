# Published Simulation-Comparison Gallery Inputs

This directory is the versioned handoff point between heavy comparison workflows
and the documentation gallery.

The documentation build should not run MF6, PETSc, or WSL-side comparison
campaigns. Instead, regenerate the comparison outside Sphinx, review the
outputs, then publish a compact artifact bundle here:

- `case.json`
- `comparison_manifest.json`
- `comparison_metrics.json`
- `observables.csv`
- optional `comparison_audit.json`
- optional `comparison_report.md`
- optional `execution_times.csv`
- optional `source_manifest.json`

Each case lives in its own subdirectory:

```text
examples/projects/09_capability_gallery/simulation_comparison/<slug>/
```

The helper command copies the required files and creates a first `case.json`:

```bash
python -m tools.doc_gallery.import_simulation_comparison \
  examples/projects/10_testbed_workflow/outputs/<campaign>/comparisons/<comparison_id> \
  --slug <slug> \
  --title "Readable Case Title" \
  --study-area "Natural N1 10 km2 testbed"
```

It can also publish every completed comparison discovered under one testbed or
benchmark output root. This is the path to use for natural-site campaigns and
for the Nançon hydrographic-network benchmark:

```bash
python -m tools.doc_gallery.import_simulation_comparison \
  --testbed-output-root examples/projects/10_testbed_workflow/outputs/boussinesq_natural_n1_10km2_testbed \
  --study-area "Natural N1 10 km2 testbed" \
  --family-key boussinesq_mf6_natural_testbed \
  --family-label "Natural-Geology MF6/Boussinesq Testbed" \
  --force

python -m tools.doc_gallery.import_simulation_comparison \
  --testbed-output-root examples/projects/11_nancon_network_physical_benchmark/outputs/nancon_network_physical_benchmark \
  --study-area "Nançon hydrographic-network benchmark" \
  --family-key nancon_hydrographic_network_benchmark \
  --family-label "Nançon Hydrographic-Network Benchmark" \
  --force
```

`tools.doc_gallery` discovers every `<slug>/case.json` in this directory. The
gallery page is then regenerated from committed artifacts only:

```bash
python -m tools.doc_gallery --only <slug>
python -m tools.doc_gallery --check --only <slug>
```

`case.json` stores page metadata and the focus simulation. A minimal file looks
like this:

```json
{
  "slug": "natural_n1_10km2_site_03_mf6_bouss",
  "title": "Natural N1 10 km2 Site 03 MF6/Boussinesq",
  "deck": "Published MODFLOW 6 and Boussinesq comparison on one natural-geology 10 km2 site.",
  "summary": "This page republishes reviewed comparison artifacts from the Boussinesq natural-geology testbed without rerunning either solver during documentation generation.",
  "study_area": "Natural N1 10 km2 testbed",
  "focus_simulation_id": "bouss_candidate",
  "comparison_family_key": "boussinesq_mf6_natural_testbed",
  "comparison_family_label": "Natural-Geology MF6/Boussinesq Testbed",
  "comparison_case_order": 30,
  "what_it_shows": [
    "How Boussinesq compares against the MODFLOW 6 reference on a reviewed natural site.",
    "How map metrics and runtime diagnostics are published from stable artifacts instead of from a doc-time solve."
  ]
}
```

When a source TOML, launcher, metric schema, or relevant solver path changes,
refresh the comparison outputs first, then replace the bundle here and run the
gallery check. A `source_manifest.json` can be used to record the hashes or
commit SHAs that justified the refresh.

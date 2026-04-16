# Doc Gallery

This toolchain generates the static illustrated capability gallery used by the
Sphinx documentation.

## Commands

Generate or refresh the committed gallery artifacts:

```bash
python -m tools.doc_gallery
```

Verify that the committed generated files are in sync with the manifest and the
source hashes:

```bash
python -m tools.doc_gallery --check
```

Generate versioned batch reports for the analytical validation suites:

```bash
python -m validation_cases.update_reports --no-show
```

Import one local mesh bundle into the canonical repository layout used by the
gallery:

```bash
python -m tools.doc_gallery.import_mesh_bundle \
  --source-bundle C:/results/HydromodPy/mesh_catchment_runs/headwater_100km2/mesh_outlet_27/mesh_catchment_outlet_27_bundle \
  --scale 100km2 \
  --variant geology_rivers_buffer30 \
  --outlet-id 27
```

Sync the repeated mesh-gallery families directly from existing batch results and
refresh the generated docs in one go:

```bash
python -m tools.doc_gallery.sync_mesh_catchment_runs --update-gallery
```

## What It Writes

The generator rewrites:

- `docs/readthedocs/source/capability_gallery/`
- `docs/readthedocs/source/_static/capability_gallery/`

The documentation build does not execute the gallery cases. It only reads the
committed `.rst`, `.png`, and `.json` artifacts generated ahead of time.

## How Cases Are Declared

Case inventory now lives in two places:

- `tools/doc_gallery/gallery_manifest.py` for generator-backed cases whose
  metadata still benefits from Python helpers or discovery code,
- `tools/doc_gallery/manifests/*.json` for small declarative inventories,
  especially stable `copy_assets` cases where adding one page should mostly be
  data entry rather than Python editing.

Each `GalleryCaseSpec` declares:

- the category and page metadata
- optional guided-doc links for onboarding
- optional key-parameter and reading-order notes
- the reproduction command shown in the docs
- the source files tracked for staleness detection
- the generator kind (`mesh_viewer`, `copy_assets`, or `validation_case`)
- the image assets and displayed metrics

For future mesh-gallery cases, the canonical repository input tree lives under
`examples/mesh_gallery/`.

- `tools/doc_gallery/import_mesh_bundle.py` copies one local bundle into that tree
- `tools/doc_gallery/sync_mesh_catchment_runs.py` bulk-refreshes repeated mesh families from `C:/results/Hydromodpy/mesh_catchment_runs/`
- `tools/doc_gallery/mesh_case_registry.py` defines the shared case schema and naming
- `tools/doc_gallery/gallery_manifest.py` auto-discovers `examples/mesh_gallery/**/case.json`

Simple committed asset-copy cases can also be declared through JSON manifests
under `tools/doc_gallery/manifests/`.

- the current `code_comparison` pages use this path,
- JSON manifests are a good fit when the generator is already known and the work
  is mostly title/summary/assets/metadata declaration,
- Python stays the right place for cases that need helper builders, discovery,
  metric formatter functions, or richer derived defaults.

Analytical validation cases are discovered automatically from
`validation_cases/analytical/`.

- `tools/doc_gallery/validation_case_registry.py` reads `metadata.toml`, the
  case `README.md`, and the global inventory in `validation_cases/README.md`
- solver coverage is inferred from `[config_files]`
- gallery pages render one common benchmark description plus solver-specific
  tabs when a case exposes more than one backend
- the validation landing page also reads committed batch reports from
  `validation_cases/reports/latest/*.json`
  refreshed through `python -m validation_cases.update_reports`

## How To Add One Case

1. For a simple `copy_assets` page, prefer adding one entry under `tools/doc_gallery/manifests/*.json`.
2. For a generated or discovered case, add the corresponding `GalleryCaseSpec` or helper builder in `tools/doc_gallery/gallery_manifest.py`.
3. Make sure the case is reproducible from versioned repository inputs.
4. Run `python -m tools.doc_gallery`.
5. Inspect the generated page under `docs/readthedocs/source/capability_gallery/cases/`.
6. Run `python -m tools.doc_gallery --check`.
7. Rebuild Sphinx with `python -m sphinx -E -a -W -b html source _build/html` from `docs/readthedocs/`.

## How To Add One Mesh Bundle Case

1. Produce one local bundle with the mesh launcher.
2. Import it into `examples/mesh_gallery/` with `python -m tools.doc_gallery.import_mesh_bundle ...`.
3. Review the generated `case.json`, `viewer_config.toml`, and `README.md`.
4. Run `python -m tools.doc_gallery`.
5. Rebuild Sphinx and inspect the new page under `capability_gallery/mesh`.

## How To Add One Validation Case

1. Add the case under `validation_cases/analytical/` with `README.md`,
   `metadata.toml`, `comparison.py`, `plotting.py`, and `run_case.py`.
2. Register the case in the inventory tables of `validation_cases/README.md`.
3. If the benchmark belongs to a new analytical family, add its equations in
   `tools/doc_gallery/validation_case_registry.py`.
4. Run `python -m tools.doc_gallery`.
5. Rebuild Sphinx and inspect the page under `capability_gallery/validation`.

## CI Regeneration Check

The repository now carries a dedicated GitHub Actions workflow:

- `.github/workflows/docs-gallery-check.yml`

Its job is intentionally narrow:

- install the lightweight Python environment required by the gallery tooling,
- run `python -m tools.doc_gallery --check`,
- fail the PR if committed gallery artifacts drift away from the declarative
  inventory or tracked source hashes.

This does not regenerate validation batch reports in CI. Those reports still
depend on heavier scientific runtimes and are refreshed explicitly when the
validation report content itself changes.

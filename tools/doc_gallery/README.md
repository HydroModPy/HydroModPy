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

Import one local mesh bundle into the canonical repository layout used by the
gallery:

```bash
python -m tools.doc_gallery.import_mesh_bundle \
  --source-bundle C:/results/HydromodPy/mesh_catchment_runs/headwater_100km2/mesh_outlet_27/mesh_catchment_outlet_27_bundle \
  --scale 100km2 \
  --variant geology_rivers_buffer30 \
  --outlet-id 27
```

## What It Writes

The generator rewrites:

- `docs/readthedocs/source/capability_gallery/`
- `docs/readthedocs/source/_static/capability_gallery/`

The documentation build does not execute the gallery cases. It only reads the
committed `.rst`, `.png`, and `.json` artifacts generated ahead of time.

## How Cases Are Declared

Case inventory lives in `tools/doc_gallery/gallery_manifest.py`.

Each `GalleryCaseSpec` declares:

- the category and page metadata
- the reproduction command shown in the docs
- the source files tracked for staleness detection
- the generator kind (`mesh_viewer`, `copy_assets`, or `validation_case`)
- the image assets and displayed metrics

For future mesh-gallery cases, the canonical repository input tree lives under
`examples/mesh_gallery/`.

- `tools/doc_gallery/import_mesh_bundle.py` copies one local bundle into that tree
- `tools/doc_gallery/mesh_case_registry.py` defines the shared case schema and naming
- `tools/doc_gallery/gallery_manifest.py` auto-discovers `examples/mesh_gallery/**/case.json`

## How To Add One Case

1. Add a new `GalleryCaseSpec` in `tools/doc_gallery/gallery_manifest.py`.
2. Make sure the case is reproducible from versioned repository inputs.
3. Run `python -m tools.doc_gallery`.
4. Inspect the generated page under `docs/readthedocs/source/capability_gallery/cases/`.
5. Run `python -m tools.doc_gallery --check`.
6. Rebuild Sphinx with `python -m sphinx -E -a -W -b html source _build/html` from `docs/readthedocs/`.

## How To Add One Mesh Bundle Case

1. Produce one local bundle with the mesh launcher.
2. Import it into `examples/mesh_gallery/` with `python -m tools.doc_gallery.import_mesh_bundle ...`.
3. Review the generated `case.json`, `viewer_config.toml`, and `README.md`.
4. Run `python -m tools.doc_gallery`.
5. Rebuild Sphinx and inspect the new page under `capability_gallery/mesh`.

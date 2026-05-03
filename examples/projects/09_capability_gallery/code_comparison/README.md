Code-comparison gallery assets generated from committed solver runs.

Regenerate the PNG and JSON files in the subfolders with:

```bash
python tools/doc_gallery/generate_code_comparison_assets.py
```

The generator reads each source run under `out/`. It rebuilds the committed
PNG files and JSON summaries under
`examples/projects/09_capability_gallery/code_comparison/`. If an
`execution_times.csv` file is present in the source run, the JSON summary also
records `wall_time_seconds` for each solver.

Refresh the ReadTheDocs static mirror and generated pages with:

```bash
python -m tools.doc_gallery
```

Then rebuild Sphinx:

```bash
python -m sphinx -b html docs/readthedocs/source docs/readthedocs/build/html
```

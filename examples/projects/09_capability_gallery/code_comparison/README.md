Code-comparison gallery assets generated from committed solver runs.

Regenerate the PNG and JSON files in the subfolders with:

```bash
python tools/doc_gallery/generate_code_comparison_assets.py
```

The source runs remain under `out/` and the doc gallery copies the generated
assets into `docs/readthedocs/source/_static/capability_gallery/code_comparison/`.

# results/export

This folder answers how a sealed run, or a summary of many runs, leaves the project in a form that others can
find and reuse. It builds the RO-Crate FAIR view of a sealed directory, copies a run or a summary out of the
tree, and packs a whole project with its data. Everything is read from the directory. The index is never
opened.

STAC and the standalone PROV view moved to `hydromodpy_annex/export/`. They are export formats of the port
(`results/exporters/`), registered by the `hydromodpy.export.format` entry points, so `format = "stac"` and
`format = "prov"` are refused unless the annex can be imported. What stays here is what RO-Crate reads: the
document built by `build_prov_document`, with its activities and identifiers. A run directory may still carry
`stac-item.json` or `prov.jsonld` written by an annex. The seal keeps not inventorying them, because they belong
to the view and the stored layout names them.

## How the work flows

1. `directory.py` reads the seal of a run or a job and builds one `FairExportContext` (`context.py`).
2. A FAIR view is one format of the export port: `rocrate` here, `stac` and `prov` in the annex. The view
   writer receives the context in its `ExportJob`, so every view describes the same seal.
3. `context.to_json` writes every FAIR view atomically, whole, through a temporary file and one rename.
4. `publish.py` copies a run or a summary out of the tree, as a directory or a tar. It writes `PUBLICATION.json`
   and redacts the host, the user and the absolute paths. `verify` checks a copy.
5. `project_package.py` writes a whole project with its data for `hmp publish --package`.
6. `summary_tables.py` and `campaign_summary.py` write the table, the page, the README and the crate of a summary.
7. `zenodo.py` renders the Zenodo deposit metadata of one sealed run: title, creators, licence, keywords,
   version and related identifiers. It writes nothing; the publication writes `.zenodo.json` beside the crate.

## The folder map

```text
export/
├── context.py           FairExportContext, AssetEntry, InputEntry, to_json
├── directory.py         context_from_directory, publication_of
├── rocrate.py           RO-Crate 1.1 metadata, declared in results/exporters
├── zenodo.py            zenodo_metadata, the deposit form of one sealed run
├── prov.py              build_prov_document and the PROV identifiers, read by RO-Crate
├── publish.py           publish, publish_project, verify
├── project_package.py   export_project, the meshes a project consumed
├── summary_tables.py    a table of runs as Parquet, CSV and GeoPackage
└── campaign_summary.py  page, README and RO-Crate of a summary
```

## Where to add what

| To add | Where |
|--------|-------|
| a view outside the wheel | a writer on the export port, like the annex, published on the `hydromodpy.export.format` entry-point group |
| a field the views share | `FairExportContext` in `context.py`, filled in `directory.py` |
| a file that a view writes | write it with `to_json` so the write stays atomic |
| something removed from a published copy | the redaction in `publish.py` |
| a column of a summary table | `summary_tables.py` |

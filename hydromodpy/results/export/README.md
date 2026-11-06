# results/export

This folder answers how a sealed run, or a summary of many runs, leaves the project in a form that others can
find and reuse. It builds FAIR views (RO-Crate, STAC, PROV) from a sealed directory, copies a run or a summary
out of the tree, and packs a whole project with its data. Everything is read from the directory. The index is
never opened.

## How the work flows

1. `directory.py` reads the seal of a run or a job and builds one `FairExportContext` (`context.py`).
2. `write_views` hands that same context to the three view writers, so the views describe the same seal.
3. `rocrate.py`, `stac.py` and `prov.py` each build their document from the context.
4. `context.to_json` writes every FAIR view atomically, whole, through a temporary file and one rename.
5. `publish.py` copies a run or a summary out of the tree, as a directory or a tar. It writes `PUBLICATION.json`
   and redacts the host, the user and the absolute paths. `verify` checks a copy.
6. `project_package.py` writes a whole project with its data for `hmp publish --package`.
7. `summary_tables.py` and `campaign_summary.py` write the table, the page, the README and the crate of a summary.

## The folder map

```text
export/
├── context.py           FairExportContext, AssetEntry, InputEntry, to_json
├── directory.py         context_from_directory, write_views, publication_of
├── rocrate.py           RO-Crate 1.1 metadata
├── stac.py              STAC Item, Collection and Catalog
├── prov.py              PROV-O JSON-LD lineage
├── publish.py           publish, publish_project, verify
├── project_package.py   export_project, the meshes a project consumed
├── summary_tables.py    a table of runs as Parquet, CSV and GeoPackage
└── campaign_summary.py  page, README and RO-Crate of a summary
```

## Where to add what

| To add | Where |
|--------|-------|
| a new FAIR view | a module here that takes a `FairExportContext`, its name in `write_views` of `directory.py` |
| a field the views share | `FairExportContext` in `context.py`, filled in `directory.py` |
| a file that a view writes | write it with `to_json` so the write stays atomic |
| something removed from a published copy | the redaction in `publish.py` |
| a column of a summary table | `summary_tables.py` |

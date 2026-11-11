# results/exporters

This folder holds the export port: how a finished run becomes a file that
other tools read. One writer class per format, registered in `export_formats`
(`registry.py`), and every file format is declared the same way, in the wheel
or out of tree. The six file formats of the wheel (CSV, GeoTIFF, NetCDF,
GeoPackage, Shapefile, VTU) live in `formats.py`; RO-Crate is declared from
`results/export/rocrate.py`; STAC and the standalone PROV view live in
`hydromodpy_annex/export/` and register by entry point.

## The contract

A format is a class of the `ExportWriter` Protocol (`port.py`). It declares
`name`, `suffix`, `writes` (the export kinds it holds, or `{"run"}` for a view
that describes the whole run), `natural` (the kinds it is the default format
of), `instants` (`"one"` or `"many"`), `reprojects`, and its method
`write(job, item, dest)`, which writes at the path it receives and returns the
paths written. The vocabulary tables of `export_spec.py` (suffix of a format,
formats of one kind, views) are derived from the declarations, never written
by hand.

`write` reaches the run through `ExportJob` (`job.py`), which holds
`ExportTarget` and everything any writer reads the same way. The identity
block of the run and the entry in `exports/index.json` come from the target,
so a writer returns its paths and both are written for it.

`destination.py` reads the `deliver_to` text of a block. It parses one
destination, names the address a file takes on it, and removes the key from a
published copy.

`[[export]].format` and `hmp export --as` take a registered name, and an
unknown name is refused with the list of what this installation serves. A
declared format whose module cannot be imported is refused with its entry
point, its target and its reason, so a view that lives in the annex is named
without the package naming it.

## The folder map

```text
exporters/
├── port.py             the ExportWriter Protocol
├── registry.py         export_formats, the builtin paths, the entry-point group
├── job.py              ExportJob and ExportTarget, what every writer reads
├── formats.py          the six file writers of the wheel
├── export_spec.py      ExportRequest, the derived tables, plan_outputs
├── vocabulary.py       names a user may export, their kind
├── request.py          export_run, export_request, regen_exports
├── destination.py      the deliver_to syntax: parse, address, remove
├── fields.py          one step, one layer and the CRS, read the same for every field writer
├── _tables.py         tables of one run read from its directory
├── mesh_layers.py     the cells, seeds and line faces of the mesh as vector layers
└── vector_layer.py    a geographic layer (catchment, networks) to a GIS file
```

## Where to add what

| To add | Where |
|--------|-------|
| a format of the wheel | a writer in `formats.py`, its dotted path in `_BUILTIN_PATHS` of `registry.py`, a case in `tests/contract/test_export_format_contract.py` |
| a plugin format, out of tree | an `ExportWriter` class published on the `hydromodpy.export.format` entry-point group, named as its `name` |
| a name a user may export | `vocabulary.py` |
| a new key of the `[[export]]` request | `ExportRequest` in `export_spec.py` |
| a rule on the output path or the file name | `plan_outputs` in `export_spec.py` |
| the file name of a view | `schema/generated_views.py`, a fact of the stored layout |
| a change to the ledger entry of an export | `results/ledger.py` |

# Export port

The export port turns a finished run into a file that other tools read. Every format is one writer class declared the same way, in the wheel or out of tree, so a view that lives in the annex is named and refused like any other. `port.py` holds the `ExportWriter` Protocol and `registry.py` holds `export_formats`.

## What a writer receives and returns

`write(job, item, dest)` receives an `ExportJob` (`job.py`), which holds the `ExportTarget` and everything any writer reads the same way, the item to write and the path to write at. It returns the list of paths it wrote. The identity block of the run and the entry in `exports/index.json` come from the target, so a writer returns its paths and both are written for it.

## What a writer declares

A format declares `name`, `suffix`, `help`, `writes` (the export kinds it holds, or `{"run"}` for a view that describes the whole run), `natural` (the kinds it is the default format of), `instants` (`"one"` or `"many"`), `reprojects` and the method `write`. The vocabulary tables of `export_spec.py` (the suffix of a format, the formats of one kind, the views) are derived from these declarations and never written by hand.

## How a writer registers

The six file formats of the wheel (CSV, GeoTIFF, NetCDF, GeoPackage, Shapefile, VTU) are declared in `formats.py`, and RO-Crate is declared from `results/export/rocrate.py`. Each is a dotted path in `_BUILTIN_PATHS`. STAC and the standalone PROV view live in `hydromodpy_annex/export/` and, like any out-of-tree format, publish an entry point named as their `name` in the `hydromodpy.export.format` group.

## What is refused and what tests it

`[[export]].format` and `hmp export --as` are read by `check_registered_name`, which refuses a name nothing serves with the list this installation serves and the entry-point group. A declared format whose module cannot be imported is refused with its entry point, its target and its reason. `tests/ports/test_export.py` runs every served format on a copy of a frozen run and checks that it writes what it declares.

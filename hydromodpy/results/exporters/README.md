# results/exporters

This folder answers how a finished run becomes a file that other tools read. There is one writer per format
(CSV, GeoTIFF, NetCDF with UGRID, VTU, Shapefile, GeoPackage). A request is planned first, and then each file is
handed to the writer of its kind. Every file lands under `runs/<run>/exports/`.

## How the work flows

1. A user writes an `[[export]]` request. `export_spec.py` reads it into an `ExportRequest` and `plan_outputs`
   lists the files it will make.
2. `vocabulary.py` holds the names a user may export and the kind of each. `list_exportable` says what one run holds.
3. `request.py` expands `"all"`, turns dates into stress periods and calls `export_run`.
4. Each file goes to the writer of its kind. A field at one date goes to GeoTIFF, Shapefile, GeoPackage or VTU.
   Several dates go to one NetCDF. A series goes to CSV. A vector layer goes to GeoPackage or Shapefile.
5. The file gets the identity block of the run, then an entry in `exports/index.json` through
   `record_derived_file` in `results/ledger.py`.
6. `regen_exports` replays the ledger.

## The folder map

```text
exporters/
├── export_spec.py     ExportRequest, ExportKind, ExportFormat, plan_outputs
├── vocabulary.py      names a user may export, their kind
├── request.py         export_run, export_request, regen_exports
├── fields.py          one step, one layer and the CRS, read the same for every field writer
├── _tables.py         tables of one run read from its directory
├── csv.py             series and budget to CSV
├── geotiff.py         fields and geographic rasters to GeoTIFF
├── netcdf.py          fields to NetCDF-4 with UGRID topology
├── vtu.py             fields to VTU, through mesh/io/vtu.py
├── shapefile.py       cell geometries with values to Shapefile
├── geopackage.py      cell geometries with values to GeoPackage
├── mesh_layers.py     the cells, seeds and line faces of the mesh as vector layers
└── vector_layer.py    a geographic layer (catchment, networks) to a GIS file
```

## Where to add what

| To add | Where |
|--------|-------|
| an export format | a module here, its name in `ExportFormat` (`export_spec.py`), its route in `request.py` |
| a name a user may export | `vocabulary.py` |
| a new key of the `[[export]]` request | `ExportRequest` in `export_spec.py` |
| a rule on the output path or the file name | `plan_outputs` in `export_spec.py` |
| a change to the ledger entry of an export | `results/ledger.py` |

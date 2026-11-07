# data/variables/geology

The geological map of the study area, as polygons or as a raster of zone codes. It comes from the
BRGM or from a file of the user. The manager returns a `LoadResult` of `FieldRecord` objects that
point to cached GeoPackage or GeoTIFF files.

The manager does not build the geology field. `loading/loader.py` takes the loaded data, rasterizes
it on the domain grid and calls `field.py`. This keeps the manager free of the project geometry.

## What a source does

- `source = "custom"` reads a vector (`.shp`, `.gpkg`, `.geojson`, `.json`), a raster (`.tif`,
  `.tiff`) or a CSV, clipped to the box (`custom.py`). A file in another CRS is clipped in its own CRS.
- `source = "brgm_1m"` builds a GeoPackage from the 1:1 000 000 national map (`apis/brgm_1m.py`).
- `source = "brgm_50k"` builds one from the 1:50 000 maps of the departments that the box touches
  (`apis/brgm_50k.py`). The departments come from `hydromodpy/catchment/administrative`.
- `apis/fgeol.py` holds what the two BRGM downloads share: the hash of a box and the lookup of the
  shapefile in an archive.

## How a map becomes a grid

`io.py` reads a source into one contract: an integer grid of codes (`0` is nodata), a mapping from
code to zone name, a transform and a CRS. `processing.py` holds the small steps it needs: zone-key
normalization, the encoding of a numeric raster, and the land-sea override.

## The folder map

```text
geology/
├── config.py       GeologyConfig, the sources and the zone options
├── manager.py      GeologyManager: the sources in order, the cache
├── custom.py       the loaders of a user file
├── io.py           vector and raster sources to the grid of codes
├── processing.py   zone keys, numeric encoding, land-sea override
├── field.py        build_geology_field, called by the loader
└── apis/           brgm_1m.py, brgm_50k.py, fgeol.py
```

## Rules

- The two BRGM cache files are named with a hash of the box rounded to two decimals. A change of
  rounding renames every cached file.
- The department lookup is imported inside the functions that use it.

## Changing the code

The tests are in `tests/unit/data/variables/geology/`. `test_geology_readers.py` writes small
files in a temporary folder and needs no network.

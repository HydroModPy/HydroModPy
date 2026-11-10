# data/variables/dem

The digital elevation model of the study area. It comes from the IGN Geoplateforme, from a local
file, or from the French departments that a region names. The variable returns a `LoadResult` of
`FieldRecord` objects that point to cached GeoTIFF files. Before the variable runs, `resolver.py`
resolves the first usable source into a `FileRecord` (path, sha256, state, nodata, origin) that the
geographic pipeline reads.

## What a source does

- `source = "file"` reads a `.tif`, `.tiff`, `.asc` or `.nc` file, or a folder holding one (`custom.py`).
  A file without a CRS is refused. The file is read where it lies and is no row of the cache. A
  copy made from it goes under `data/blobs/dem/file/`.
- A `file` or `url` source takes `state = "raw"` (the default) or `state = "conditioned"`. `raw` means
  HydroModPy conditions the DEM itself. `conditioned` means another tool filled or breached it, so
  HydroModPy skips its own conditioning and still computes the D8 directions and the accumulation. An
  API source has no `state` key: a provider delivers a raw DEM.
- `source = "ign_geoplateforme_dem"` downloads from the Geoplateforme. With `dataset = "bd-alti"`
  (the default, 25 m) the variable builds the DEM from the archives of the departments that the
  study area touches: `apis/ign_dem_fr.py` finds them, `apis/geoplateforme_download.py` downloads
  and extracts them, and `apis/_bdalti_archive_index.py` indexes the BD ALTI archives. The
  departments come from `hydromodpy/catchment/administrative`. With `dataset = "rge-alti"` (5 m by
  default, 1 m allowed) it builds the DEM from WMS-Raster tiles (`apis/geoplateforme_wms.py`). All
  three datasets are downloaded by the class of the DataSource port registered under
  (dem, ign_geoplateforme_dem) in apis/ign_dem_fr.py; the variable gives it the data folder and
  writes the sidecar of the file it returns.
- The cache is indexed by box, with no time dimension. A download needs the data folder of the
  call, and is refused without one: nothing is written under the cache of the user.

## The folder map

```text
dem/
├── config.py     DemConfig, the sources and the French region and department selectors
├── variable.py    DemVariable: the sources in order, the cache, the extent
├── custom.py     the loaders of a user DEM
├── resolver.py   the resolved FileRecord of [[data.dem.sources]], with its state, found before any variable runs
└── apis/
    ├── ign_dem_fr.py              discovery of the department archives (the largest file)
    ├── geoplateforme_download.py  download and extraction of an archive
    ├── geoplateforme_wms.py       elevation tiles by WMS, one request per tile
    └── _bdalti_archive_index.py   the BD ALTI 25 m archive index
```

## Where to start

| To change | Open first |
|---|---|
| how a tile of the WMS answer is checked | `apis/geoplateforme_wms.py`, `_read_answer` |
| which departments a box needs | `apis/ign_dem_fr.py`, `find_departments_in_bbox` calls |
| the size guard on a bootstrap box | `resolver.py` |
| the accepted user file formats | `custom.py` |

## Rules

- The resolver runs before any variable. It must not need the cache rows. It still needs the data
  folder to download into.
- The department lookup is imported inside the functions that use it, so that geopandas loads only
  for a French source.

## Changing the code

The tests are in `tests/unit/data/variables/dem/`.

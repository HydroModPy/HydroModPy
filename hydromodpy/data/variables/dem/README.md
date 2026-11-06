# data/variables/dem

The digital elevation model of the study area. It comes from the IGN Geoplateforme, from a local
file, or from the French departments that a region names. The manager returns a `LoadResult` of
`FieldRecord` objects that point to cached GeoTIFF files.

## What a source does

- `source = "custom"` reads a `.tif`, `.tiff`, `.asc` or `.nc` file, or a folder holding one (`custom.py`).
  A file without a CRS is refused.
- `source = "ign_geoplateforme_dem"` downloads from the Geoplateforme. With `dataset = "bd-alti"`
  (the default, 25 m) the manager builds the DEM from the archives of the departments that the
  study area touches: `apis/ign_dem_fr.py` finds them, `apis/geoplateforme_download.py` downloads
  and extracts them, and `apis/_bdalti_archive_index.py` indexes the BD ALTI archives. The
  departments come from `hydromodpy/spatial/administrative`. With `dataset = "rge-alti"` (5 m by
  default, 1 m allowed) it builds the DEM from WMS-Raster tiles (`apis/geoplateforme_wms.py`).
- The cache is indexed by box, with no time dimension.

## The folder map

```text
dem/
├── config.py     DemConfig, the sources and the French region and department selectors
├── manager.py    DemManager: the sources in order, the cache, the extent
├── custom.py     the loaders of a user DEM
├── resolver.py   fills [geographic].dem_init_path from [[data.dem.sources]] before any manager runs
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

- The resolver runs before any manager. It must not need the cache.
- The department lookup is imported inside the functions that use it, so that geopandas loads only
  for a French source.

## Changing the code

The tests are in `tests/unit/data/variables/dem/`.

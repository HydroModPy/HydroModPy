# data/variables/hydrography

The river network of the study area. It comes from BD TOPAGE, EU-Hydro, OpenStreetMap or a file of
the user. The variable clips it to the extent, rasterizes it, and returns a `LoadResult`.

## Sources

- `file` reads a vector or a raster network from a file or a folder (`custom.py`).
- `bdtopage`, `euhydro` and `osm` are `DataSource` classes (`apis/`). They share one shape
  (`apis/features.py`): a feature table over a box in WGS84, with no time axis and nothing written
  under the request folder. A subclass names its source and hosts, checks its own options, and says
  how to download a box.
- The name of a source is resolved by `hydromodpy/data/source/registry.py`. No module of this
  folder holds the list of names. `api_source.py` turns one `[[data.hydrography.sources]]` entry
  into a network, and the variable and the resolver both call it.

## What the variable keeps

A source knows nothing of the data cache. The variable owns the superset lookup, the sidecar of a
download, the clip to the mask and the rasterization of a field. What the source reports it was
asked (the BD TOPAGE layer, the OSM waterway types) is written in the sidecar, and a row recorded
for another question is a miss. A BD TOPAGE network carries a
permanence column, and the variable writes the permanent reaches as a separate vector (the
reference of the permanent network, `source/permanence.py`). That copy has no sidecar, so it is no
row of the cache.

## The folder map

```text
hydrography/
├── config.py        HydrographyConfig and the source sections
├── variable.py       HydrographyVariable: load, cache, clip, rasterize, permanent network
├── api_source.py    one source entry to one network
├── custom.py        a user network, vector or raster
├── resolver.py      the path of the network map that a diagnostic reads, before any variable runs
└── apis/            bdtopage.py, euhydro.py, osm.py, features.py (the shared shape)
```

## Where to start

| To change | Open first |
|---|---|
| a provider call or its options | `apis/<provider>.py` |
| how a box is answered from the cache | `variable.py`, `fetch_network_through_cache` |
| the rasterization of a field | `variable.py`, `_rasterize` |
| which path the diagnostic reads | `resolver.py`, `resolve_network_map_path` |

## Rules

- The resolver imports no variable. It reaches a download through `api_source.py`.

## Changing the code

The tests are in `tests/unit/data/variables/hydrography/`.

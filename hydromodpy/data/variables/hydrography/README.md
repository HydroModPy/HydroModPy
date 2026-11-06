# data/variables/hydrography

The river network of the study area. It comes from BD TOPAGE, EU-Hydro, OpenStreetMap or a file of
the user. The manager clips it to the extent, rasterizes it, and returns a `LoadResult`.

## Sources

- `custom` reads a vector or a raster network from a file or a folder (`custom.py`).
- `bdtopage`, `euhydro` and `osm` are `DataSource` classes (`apis/`). They share one shape
  (`apis/features.py`): a feature table over a box in WGS84, with no time axis and nothing written
  under the request folder. A subclass names its source and hosts, checks its own options, and says
  how to download a box.
- The name of a source is resolved by `hydromodpy/data/source/registry.py`. No module of this
  folder holds the list of names. `api_source.py` turns one `[[data.hydrography.sources]]` entry
  into a network, and the manager and the resolver both call it.

## What the manager keeps

A source knows nothing of the DuckDB cache. The manager owns the superset lookup, the
registration, the clip to the mask and the rasterization of a field. A BD TOPAGE network carries a
permanence column, and the manager writes the permanent reaches as a separate vector (the
reference of the permanent network, `source/permanence.py`).

## The folder map

```text
hydrography/
├── config.py        HydrographyConfig and the source sections
├── manager.py       HydrographyManager: load, cache, clip, rasterize, permanent network
├── api_source.py    one source entry to one network
├── custom.py        a user network, vector or raster
├── resolver.py      the path of the network map that a diagnostic reads, before any manager runs
└── apis/            bdtopage.py, euhydro.py, osm.py, features.py (the shared shape)
```

## Where to start

| To change | Open first |
|---|---|
| a provider call or its options | `apis/<provider>.py` |
| how a box is answered from the cache | `manager.py`, `fetch_network_through_cache` |
| the rasterization of a field | `manager.py`, `_rasterize` |
| which path the diagnostic reads | `resolver.py`, `resolve_network_map_path` |

## Rules

- The resolver imports no manager. It reaches a download through `api_source.py`.

## Changing the code

The tests are in `tests/unit/data/variables/hydrography/`.

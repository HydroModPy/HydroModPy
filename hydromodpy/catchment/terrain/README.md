# Terrain port

The terrain port routes water over a DEM for the rest of HydroModPy and hides the library that does the routing. `port.py` holds the Protocol, the product types and the checks the engines share, and `registry.py` holds `terrain_engines`. An engine needs `port.py` and `core.exceptions` and nothing else of HydroModPy.

## What an engine receives and returns

`condition_dem(dem, method, extent, out)` removes the depressions and returns a `ConditionedDem`. `drainage_directions(conditioned, out)` writes the D8 pointer, a `DrainageDirections`. `flow_accumulation(directions, units, transform, out)` writes a `FlowAccumulation`. `stream_network(accumulation, threshold, out)` keeps the cells above a threshold, a `StreamNetwork`. `delineate(accumulation, outlets, out_dir, snap_distance_m, snap, layout)` snaps each outlet and writes its mask and boundary, one `Catchment` per outlet.

Every member writes where the caller says, and every product carries its units, its transform, its pointer convention and its CRS. The conditioning method is `fill`, `breach`, a `CappedBreach` or `provided`. A `provided` DEM was conditioned by another tool and declared with `state = "conditioned"` on its `[[data.dem.sources]]` entry, so `ConditionedDem.provided(path)` wraps it and no engine conditions it, and `condition_dem` refuses `provided`.

## What an engine declares and how it registers

An engine is a class with `engine_id`, `engine_version`, `engine_digest()` and the five members. Raise `engine_version` when the products of an engine change for one request. The two built-in engines are dotted paths in `_BUILTIN_PATHS`: `whitebox_workflows`, the default because every number of the repository was produced with it, and `numpy_d8`, a reference engine in Python loops with fill only. A third party publishes an entry point named like its `engine_id` in the `hydromodpy.terrain.engine` group. A built-in name is refused, and a plug-in that fails to load is skipped with a warning.

## What is refused

`[geographic] terrain_engine` is read by `check_registered_name`, which refuses a name nothing serves with the names served and the group. An option an engine cannot serve raises `TerrainCapabilityError`, a product it cannot use `TerrainProductError`, and a request that makes no sense `TerrainRequestError`. `tests/ports/test_terrain.py` runs on every engine the registry resolves.

## Facts a caller must not guess

- `ln` is the natural logarithm, and `stream_network` refuses a transformed accumulation, because a threshold in cells on an `ln` raster selects nothing.
- An accumulation counts the cell itself, so a headwater reads 1 and an outlet that drains the whole grid reads the number of cells.
- `snap_distance_m` is the width of a square window, with a half-width of `floor(d / (2 * cell))` cells on each axis. One cell snaps nowhere, and 100 m on a 25 m grid can move an outlet 70.7 m on the diagonal.
- The D8 table is `D8_WBT_OFFSETS` and starts at the north-east. The ESRI table is one octant away, and a mix-up gives plausible paths beside the talweg.
- Masks and pointers use `-32768` for an absent cell, as Whitebox writes it. An accumulation uses it as nodata too, never 0, because `ln(1)` is 0.
- A transformed accumulation is refused where a snap window holds `ln(1 049 558)` or more, because from that count float32 gives the same `ln` to two neighbouring counts. A 25 m grid reaches it at about 656 km2 of upstream area.
- A nodata hole is no drainage target, so a depression whose only low way out crosses a hole stays a depression on both engines.
- `max_depth_m` of a capped breach is the cumulative lowering along one path and `max_distance_m` counts cells, so a diagonal path can be 1.41 times longer. `ConditionedDem.breach_report` says how much deeper a cell was cut.
- A DEM declared `conditioned` may keep cells D8 cannot route. `undrained.py` counts them, and a run that reads such a product warns with the two counts.

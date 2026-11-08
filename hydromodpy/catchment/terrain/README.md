# catchment/terrain

This package is the terrain port. It routes water over a DEM for the rest of HydroModPy and hides the library that does
the routing. An engine is a class with `engine_id`, `engine_version`, `engine_digest()` and five members.

- `condition_dem(dem, method, extent, out)` removes the depressions and returns a `ConditionedDem`.
- `drainage_directions(conditioned, out)` writes the D8 pointer, a `DrainageDirections`.
- `flow_accumulation(directions, units, transform, out)` writes a `FlowAccumulation`.
- `stream_network(accumulation, threshold, out)` keeps the cells above a threshold, a `StreamNetwork`.
- `delineate(accumulation, outlets, out_dir, snap_distance_m, snap, layout)` snaps each outlet and writes its mask and
  boundary, one `Catchment` per outlet.

Every member writes where the caller says. Every product carries what a reader needs to use it, which is the units,
the transform, the pointer convention and the CRS. An option an engine cannot serve raises `TerrainCapabilityError`.
A product it cannot use raises `TerrainProductError`, and a request that makes no sense raises `TerrainRequestError`.

The conditioning method is `fill`, `breach`, a `CappedBreach`, or `provided`. A `provided` DEM is one that another tool
conditioned. No engine runs for it. `ConditionedDem.provided(path)` wraps the file and reads its CRS, and the four other
members route it like any conditioned DEM. `condition_dem` refuses `provided` with `TerrainRequestError`, and nothing
here checks that the DEM has no depression left.

Two engines ship. `whitebox_workflows` is the default, because every number of the repository was produced with it, and
it calls the Whitebox backend of `catchment/delineation`. `numpy_d8` is a reference engine written as Python loops, with
fill only. The two are substitutable. They agree cell for cell on the valley of the contract suite. On `DEM_gouville_25m.tif`
they differ by a factor 2.5 on the area of a catchment, because they resolve flat areas at different stages.

`registry.py` resolves an engine id to a class. A third party adds an engine on the entry point group
`hydromodpy.terrain.engine`, with an entry point named like the `engine_id`. A built-in name is refused, and a plug-in
that fails to load is skipped with a warning. Such an engine needs `port.py` and `core.exceptions` and nothing else of
HydroModPy. `tests/contract/test_terrain_engine_contract.py` runs on every engine the registry resolves.

## Facts a caller must not guess

- `ln` is the natural logarithm. A threshold in cells on an `ln` raster selects nothing, so `stream_network` refuses a
  transformed accumulation.
- An accumulation counts the cell itself, so a headwater reads 1 and an outlet that drains the whole grid reads the
  number of cells.
- `snap_distance_m` is the width of a square window, with a half-width of `floor(d / (2 * cell))` cells on each axis.
  A value of one cell snaps nowhere, and 100 m on a 25 m grid can move an outlet 70.7 m on the diagonal.
- The D8 table is `D8_WBT_OFFSETS`. It starts at the north-east. The ESRI table is one octant away from it, and a mix-up
  gives plausible paths that run beside the talweg. `tests/unit/catchment/algorithms/test_stream_dem_agreement.py`
  tilts a plane in each direction and reads back the code Whitebox writes.
- Masks and pointers use `-32768` for an absent cell, as Whitebox writes it. An accumulation uses the same value as
  nodata, and never 0, because `ln(1)` is 0 and a headwater would read as a hole.
- A transformed accumulation is refused where an outlet snaps and the window holds a stored value of `ln(1 049 558)` or
  more. From that count float32 gives the same `ln` to two neighbouring counts, and a snap would tie on cells of
  different areas. The bound was found by scanning every integer. A 25 m grid reaches it at about 656 km2 of upstream
  area. It was measured for bare counts only, so a transformed accumulation has to be in cells.
- A nodata hole is no drainage target. A depression whose only low way out crosses a hole stays a depression, on both
  engines.
- `max_depth_m` of a capped breach is the cumulative lowering along one path, and `max_distance_m` counts cells along
  the path. A diagonal path can be 1.41 times longer than the distance says. A cell can be cut deeper than `max_depth_m`,
  and `ConditionedDem.breach_report` says by how much.

## Files

| file | holds |
|------|-------|
| `port.py` | the Protocol, the product types and the checks both engines share |
| `registry.py` | `terrain_engines`, the registry of engines |
| `artifacts.py` | the readbacks of the files an engine wrote, and the writer of the two outlet point layers |
| `d8.py` | the receiver of each cell of a D8 pointer raster |
| `numpy_engine.py` | `NumpyTerrainEngine` and its kernels, the priority flood, the steepest descent and the Kahn sweep |
| `whitebox_engine.py` | `WhiteboxTerrainEngine`, and the measure of a capped breach |

`port.py` imports `core.exceptions`, and `artifacts.py` inside three functions. `artifacts.py` reads the constants of
`port.py`, so a module-level import the other way would be a cycle. `WhiteboxTerrainEngine.__init__` imports
`catchment.delineation` when it is given no backend, so a third-party engine and the numpy engine never load Whitebox.
`tests/unit/architecture/test_terrain_port_stands_alone.py` checks these imports.

The tests are in `tests/unit/catchment/terrain/`, one file per module. A new member of the port is a method of the
Protocol, and both engines must serve it. Raise `engine_version` when the products of an engine change for one request.

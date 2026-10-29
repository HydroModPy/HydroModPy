# spatial/lake_bed

This package rebuilds the bed of a lake from a bathymetry raster, so the MODFLOW 6 grid holds a real basin instead of a
flat reservoir. The bathymetry is much finer than the mesh. So the package averages it onto the cells of the lake, then
remaps the elevations in one pass, by area-weighted quantiles, so the lake fills the way its abacus says. The abacus is the table of stage against wetted
area that the user gives for the lake. Last, it re-grades each mesh column so the bed sits at the carved elevation.

The package holds only the numbers. It reads no config and builds no MODFLOW object.

## How the work flows

1. `regrid.py` gives each lake cell the mean of the bathymetry pixels whose centre falls in the cell. A cell with no
   pixel centre gets a bilinear sample at its centroid.
2. `abacus.py` reconciles that bed to the abacus. The deepest cells get the lowest stages, with the plan area of each
   cell as the weight, so the area below each elevation matches the abacus. The pattern of deep and shallow cells stays.
3. `carve_math.py` re-grades one column of layers around the carved bed, keeping a minimum thickness on every layer and
   the aquifer base fixed.
4. `abacus.py` can also flood the carved bed again and return the stage, volume and area it really gives, to compare
   with the abacus of the user.

```text
bathymetry raster + lake cells
        |
        |  regrid.py        cell_bed_from_surface         mean of the pixels in each cell
        v
   raw bed per cell
        |
        |  abacus.py        reconcile_bed_to_abacus       quantile map onto the abacus
        v
   carved bed per cell
        |
        |  carve_math.py    regrade_column_to_bed         new layer bottoms of each column
        v
   new top and botm of the lake columns
```

## The folder map

```text
lake_bed/
├── regrid.py       bathymetry onto mesh cells, and reconstruct_lake_bed, the two steps for one lake
├── abacus.py       reconcile a bed to the abacus, and simulate the abacus of a bed
└── carve_math.py   re-grade the layers of one column around the bed
```

## Where to start

| To change | Open first |
|-----------|------------|
| how the bathymetry is averaged on a cell | `cell_bed_from_surface` in `regrid.py` |
| how the bed follows the abacus | `reconcile_bed_to_abacus` in `abacus.py` |
| the check of the carved bed against the abacus | `simulate_abacus` in `abacus.py` |
| the thickness of the layers under a lake | `regrade_column_to_bed` in `carve_math.py` |
| the layers when the shore cells stay active | `regrade_column_active_top` in `carve_math.py` |

## Rules between the folders

- `carve_math.py` imports nothing from HydroModPy.
- `abacus.py` reads only `hydromodpy.core.logging`.
- `regrid.py` reads `abacus.py` and two modules at the top of `spatial/`, `surface.py` and `surface_sampling.py`. It
  takes the mesh as an argument and imports no mesh module.
- The package imports no layer above `spatial`, and no other package of `spatial`.

The layer matrix is checked by `tests/unit/architecture/`.

## What lives outside the package

The caller is `carve_lake_bed` in `hydromodpy/solver/modflow6/builders/lake.py`. It reads the `bed_reconstruction` table
of each lake, picks the lake cells and the abacus, calls the three modules, and writes the new `top` and `botm` into the
solver mesh. It imports the modules inside the function, so a run without a lake bed never loads them.
`hydromodpy/solver/modflow6/build.py` calls it.

## Changing the code

The tests follow the layout of the code under `tests/unit/lake_bed/`: `test_regrid.py`, `test_abacus.py` and
`test_carve_math.py`. They build their mesh, bathymetry and column stack with `tests/_helpers/lake_bed_cases.py`. The
carve as a whole, with the solver mesh, is tested in `tests/unit/solver/modflow6/test_lake_bed_carve.py`.

The CI job `mesh-coverage` in `.github/workflows/main-ci.yml` fails when the coverage of this package drops below 99.2,
the floor of the line `coverage report --include='hydromodpy/spatial/lake_bed/*'`. The floors only go up.

```bash
pytest tests/unit/lake_bed tests/unit/solver/modflow6/test_lake_bed_carve.py -q
```

A new key of `bed_reconstruction` is a field of the lake config, not of this package, and the parameter reference is
built from that model.

## Documentation

The keys are in `docs/source/reference/parameters/flow/sinks_sources/lakes.md`, under the `bed_reconstruction` table.
The theory of the active shore, where the carved bed becomes the cell top, is in `docs/source/theory/exits/lakes.md`.

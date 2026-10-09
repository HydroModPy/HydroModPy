# Model a catchment outside France

```{hmp-task}
Task
: Set up and run a catchment where BD Topage, Hub'Eau, SIM2 and BRGM do not reach.

Time
: Half an hour for the data, ten seconds for the run.

Needs
: A DEM of your area, an outlet, and your own estimate of recharge.

Gives
: A steady run, and a river network from a European or a global source.
```

Most of the downloading sources of HydroModPy are French services. They return nothing, or
nothing useful, outside France. The model itself has no such limit: the solver, the mesh, the
catchment delineation and the figures work in any projected CRS. This page says what to use
instead, and builds a catchment of the Belgian Ardennes from a global DEM, with no French
service at all.

## 1. What works where

A data variable takes a list of sources, `[[data.<variable>.sources]]`. `custom` reads your own
file and works anywhere. The rest are providers. {doc}`../reference/data-sources` gives the
coverage, the licence and the limits of each one. The table below sorts them.

| Variable | Works anywhere | Covers France only |
|---|---|---|
| DEM | `custom`: a GeoTIFF, an ASC or a NetCDF in a projected CRS | `ign_geoplateforme_dem`: BD ALTI and RGE ALTI |
| Geology | `custom`: a vector map, a GeoTIFF or a CSV of points | `brgm_1m`, `brgm_50k` |
| Stream network | `custom`, `osm` (the waterways of OpenStreetMap in a box), `euhydro` (the 39 EEA countries, 27.4 to 71.4° N and 31.6° W to 44.8° E, and the French overseas departments) | `bdtopage` |
| Gauged discharge, groundwater levels, intermittency, water quality | `custom` | `hubeau` |
| Precipitation, ETP | `custom` | `sim2`, `explore2` |
| Recharge, runoff, temperature, wind, humidity, radiation, soil moisture | `custom`. For recharge also `synthetic`, a series you generate | `sim2` |
| Sea level | `custom`, `constant` | `shom` |
| Lakes, substratum, soil capacity, crossings | `custom` | none |

Three consequences:

- **The DEM and the network are the two inputs you can get anywhere.** A steady run needs the DEM
  and a recharge rate and nothing else.
- **No service gives you a forcing.** Recharge, rain and ETP come from your own files, or from a
  constant. HydroModPy does not estimate them for another country.
- **A calibration needs your own gauge.** Hub'Eau serves French stations only. A discharge
  series of your own goes in as a `custom` hydrometry source, as in {doc}`use-your-own-files`.

A French source asked outside its coverage does not refuse. BD Topage on a box in Belgium
returned `fetched 0 reaches` and wrote an empty result, and on a box at the border it returned one
reach. No error was raised either time. Check what a source returned before you use it.

## 2. Cut a DEM

No DEM service of HydroModPy works outside France, so you bring the file. The Copernicus GLO-30
model is global, at 30 m, and published as open GeoTIFF tiles. The script
{download}`recipes/cut_dem.py` reads only the window you ask for and reprojects it:

```bash
python cut_dem.py 5.28 50.18 5.52 50.36 EPSG:25831 dem_ardennes_25831.tif
```

```text
dem_ardennes_25831.tif: 592 x 686 cells of 30 m in EPSG:25831
```

The four numbers are the west, south, east and north of the box in degrees, and the box must sit
in one tile. The CRS is a projected CRS in metres that suits your area: a UTM zone, or the national
grid of your country. The file written here is 1.3 MB.

Write the CRS into the file, as the script does. A DEM without a CRS is labelled `EPSG:2154`, the
French grid, and the catchment then lands in the wrong place or carries no CRS. Check the licence
of the DEM you use. A file you supply has no licence for HydroModPy until you write one in a sidecar
`dem_ardennes_25831.tif.json`, for example `{"license": "CC-BY-4.0"}`, and the licence of your runs
depends on it ({doc}`share-a-run`).

Put the file in the workspace, in `data/dem/`.

## 3. Find an outlet

The catchment is cut upslope of an outlet point in the CRS of the project. Without a map at hand,
the capability `terrain-delineate` of {doc}`run-in-the-background` gives you the flow accumulation
of the DEM. Run it once with any point, for example the lowest cell, then read the accumulation:

```python
import numpy as np
import rasterio

acc = rasterio.open("job/outputs/flow_accumulation.tif")
cells = np.exp(acc.read(1).astype("float64"))      # the raster holds ln(cells)
cells[acc.read(1) < -1000] = 0                       # outside the DEM
candidates = np.argwhere((cells > 8000) & (cells < 9000))
row, col = candidates[0]
print(acc.xy(row, col))                              # an outlet of about 7 km2
```

At 30 m, 8 000 cells make about 7 km². Pick a point on the network, delineate again with it as the
outlet, and check the area before you go further. The outlet used below,
`(673044.6, 5578859.6)` in `EPSG:25831`, gives a catchment of 7.9 km².

## 4. Write the file and run

```{literalinclude} recipes/outside_france.toml
:language: toml
:lines: 9-70
```

The whole file is {download}`recipes/outside_france.toml`. It is step 1 of the staircase with
three changes: the CRS, the outlet and the DEM. It asks for no `[data]` section and no download.

```bash
hmp run outside_france.toml
```

```text
[WARNING] Simulated discharge is baseflow only: the run has no runoff forcing, so it underestimates a gauged total streamflow.
Run completed: ardennes_steady [06000b30] 10s
```

The warning is true here: there is no runoff series, so the discharge counts the baseflow
only. Read it as the model telling you what it was not given.

```{image} ../_static/figures/guides/outside_france_watertable_depth_map.webp
:alt: Map of the depth of the water table in the catchment of the Belgian Ardennes, from 0 to 30 m, with the outlet at the west edge.
:class: only-light
```

```{image} ../_static/figures/guides/outside_france_watertable_depth_map-dark.webp
:alt: Map of the depth of the water table in the catchment of the Belgian Ardennes, from 0 to 30 m, with the outlet at the west edge.
:class: only-dark
```

The map is a first run: one K, one recharge rate set at 0.9 mm/day without a source, and a
constant thickness of 30 m. It shows that the chain works, not that the model is right. The
steps that make it right are the ones of {doc}`../get-started/staircase/index`, with your own data.

## 5. Add a stream network

`hmp data get` fetches a network over a box without a project. The box is in the CRS you name:

```bash
hmp data get hydrography --source euhydro --bbox=5.28,50.18,5.52,50.36 --crs EPSG:4326 --out eu
hmp data get hydrography --source osm     --bbox=5.28,50.18,5.52,50.36 --crs EPSG:4326 --out osm
```

On the box of the DEM, 18 by 20 km, `osm` returned 584 waterway lines and `euhydro` 77 reaches.
OpenStreetMap is the denser one, and its licence, ODbL, asks you to share a derived database under
the same licence. EU-Hydro is photo-interpreted at about 1:50 000, and its licence is the one of
the Delegated Regulation 1159/2013. The file the command writes carries the licence in its sidecar.

To use a network in a run, name it in the file. This variant of the file above reads EU-Hydro:

```toml
base_config = "outside_france.toml"

[simulation]
name = "ardennes_euhydro"

[data]
types = ["hydrography"]

[[data.hydrography.sources]]
source = "euhydro"
```

The download is cached in `data/hydrography/` and reused. The network becomes the mapped
reference network of the run: the figure `hydrographic_network_reference` and the export of the
same name read it. It does not change the flow: the two runs of this page give the same water table,
cell by cell. A network is a reference to compare with, never an input of the model.

## What can go wrong

| Symptom | Cause | Fix |
|---|---|---|
| The catchment is in the wrong place, or the exports have no CRS | The DEM has no CRS, so it was labelled `EPSG:2154` | Write the CRS in the file. {doc}`use-your-own-files` lists the rules of each loader |
| `data.types lists 'dem' but the file has no [data.dem] section. Add the section with its sources, or remove 'dem' from data.types.` | `dem` in `data.types` with the DEM given by `dem_init_path` only | Leave `dem` out of `data.types`, as above, or declare `[[data.dem.sources]]` |
| `[WFS] BD Topage sa:TronconHydrographique_FXX_Topage2026: fetched 0 reaches` and `empty` | The box is outside the coverage of the French service, which does not refuse | Use `osm`, `euhydro` or a `custom` file |
| `The box must sit inside one one-degree tile. Cut two boxes.` | `cut_dem.py` was given a box that crosses a degree line | Cut two boxes, or a smaller one |
| `Simulated discharge is baseflow only: the run has no runoff forcing, …` | No runoff series | Give a `custom` runoff series, or read the discharge as baseflow |
| The outlet moved far, or the catchment is huge | The point snapped onto a larger river | Take a smaller `snap_dist`, or a point on a tributary, and check the area |

## Next

- The data of a project, variable by variable: {doc}`get-the-data`.
- Your own files and what each loader expects: {doc}`use-your-own-files`.
- The sources, their licences and their limits: {doc}`../reference/data-sources`.
- Build the model step by step: {doc}`../get-started/staircase/index`.

# Hand a run to a GIS colleague

```{hmp-task}
Task
: Give the maps of a run to someone who works in a GIS, as files they open without HydroModPy.

Time
: Under a minute to write, ten to check.

Needs
: A completed run.

Gives
: A folder of GeoPackages and GeoTIFFs in the CRS you choose.
```

A GIS user wants layers, not a catalog. HydroModPy writes the maps of a run as standard files:
GeoTIFF for rasters, GeoPackage and Shapefile for vectors, NetCDF for chronicles, and VTU for
ParaView. This page writes the set a GIS needs, says what each file holds, and lists what to tell
the person who receives it.

## 1. Write the files

The run is `nancon_step4_transient`, the transient run of example 04. The date `2002-10-15` is a
dry month and `2002-04-15` a wet one.

::::{tab-set}

:::{tab-item} Command line

```bash
hmp export nancon_step4_transient watershed hydrographic_network_reference \
    --format geopackage --folder for_gis
hmp export nancon_step4_transient simulated_active_network \
    --time 2002-10-15 --format geopackage --folder for_gis
hmp export nancon_step4_transient watertable_depth seepage_mask \
    --time 2002-04-15 2002-10-15 --format geotiff --folder for_gis
hmp export nancon_step4_transient watertable_depth --time 2002-10-15 \
    --crs EPSG:4326 --format geotiff --folder for_gis --file watertable_depth_wgs84.tif
```

Each command prints the files it wrote. `--list` prints what a run can export, by kind:

```bash
hmp export nancon_step4_transient --list
```
:::

:::{tab-item} In the run file

The same files, written when the run finishes, from {download}`recipes/hand_off_to_gis.toml`:

```{literalinclude} recipes/hand_off_to_gis.toml
:language: toml
:lines: 7-
```

```bash
hmp run hand_off_to_gis.toml
```
:::

::::

A relative `--folder` is read from the `share/` folder of the project, so the files land in
`share/for_gis/`:

```text
hydrographic_network_reference.gpkg
seepage_mask_2002-04-15.tif
seepage_mask_2002-10-15.tif
simulated_active_network_2002-10-15.gpkg
watershed.gpkg
watertable_depth_2002-04-15.tif
watertable_depth_2002-10-15.tif
watertable_depth_wgs84.tif
```

Name the format. Without `--format`, several dates of a field go to one NetCDF file, which a GIS
does not read as a map. With `--format geotiff`, each variable and each date is its own file.

```{image} ../_static/figures/staircase/step5/watertable_depth_map.webp
:alt: Map of the depth of the water table in the Nançon catchment in October 2002, drawn from the run.
:class: only-light
```

```{image} ../_static/figures/staircase/step5/watertable_depth_map-dark.webp
:alt: Map of the depth of the water table in the Nançon catchment in October 2002, drawn from the run.
:class: only-dark
```

The colleague should see this map in their GIS, when they load `watertable_depth_2002-10-15.tif`.

## 2. What each file holds

| File | Layer | Content |
|---|---|---|
| `watershed.gpkg` | `watershed`, 1 polygon | The catchment outline. One attribute, `VALUE` |
| `hydrographic_network_reference.gpkg` | `hydrographic_network_reference`, 227 lines | The mapped network you gave the project, with the attributes of your file. It is a reference, not a result |
| `simulated_active_network_2002-10-15.gpkg` | `simulated_active_network`, 610 polygons | The cells where the model puts a flowing stream that month. Attributes `cell_id` and `simulated_active_network`, always 1: a cell that is not in the network is not written |
| `watertable_depth_<date>.tif` | one band | Depth of the water table below the ground, in metres |
| `seepage_mask_<date>.tif` | one band | 1 where the water table reaches the ground, 0 elsewhere |

The vectors are in the CRS of the project, `EPSG:2154` for example 04. The rasters are too, on the
grid of the mesh: 154 rows and 139 columns of 75 m. The grid covers the catchment and its buffer,
so every cell has a value, and the cells outside the outline of `watershed.gpkg` are the buffer. The file `watertable_depth_wgs84.tif` is
reprojected to `EPSG:4326` for a web map, with a pixel of 0.00086 degree. `--resolution` sets the
pixel of a GeoTIFF in the units of the output CRS. `--layer N` picks a model layer for a field that
has several, 0 being the top one.

Every GeoTIFF is `float64`, with the nodata value `-9999`, and carries its facts as tags: `HMP_VARIABLE`,
`HMP_UNITS`, `HMP_PERIOD` (here `2002-10`, the month the date falls in), `HMP_SIM_ID` and
`HMP_TIMESTAMP`. A GIS that reads the tags shows them beside the layer.

The same data in other formats: `--format shapefile` writes a Shapefile with its `.prj`, `.cpg`,
`.dbf` and `.shx`. `--format netcdf` writes a chronicle. `--format vtu` writes the mesh for ParaView.

## 3. What HydroModPy does not write

No style file and no QGIS project is written. The layers open unstyled, with the default colours
of the GIS. HydroModPy has no command that makes either. The figures in `runs/<run>/figures/` are
PNG images, drawn by HydroModPy for reading, and are not layers.

If your colleague wants a map with the colours of the figures, they style the layers once in their
GIS and keep the style on their side.

## 4. Check before you send

Open two files with the tools your colleague will use, or any GDAL tool:

```python
import geopandas as gpd
import rasterio

print(gpd.read_file("share/for_gis/simulated_active_network_2002-10-15.gpkg").crs)
with rasterio.open("share/for_gis/watertable_depth_2002-10-15.tif") as r:
    print(r.crs, r.nodata, r.tags()["HMP_UNITS"])
```

```text
EPSG:2154
EPSG:2154 -9999.0 m
```

Then tell them four things, in the message that carries the files:

- the CRS of the vectors and of each raster;
- that `-9999` is nodata, that the grid is larger than the catchment, and the unit of each raster;
- the date or period each file describes: the maps of a transient run are one month;
- the licence of the inputs. The run records it, and a licence that no input states reads
  `LicenseRef-undetermined`: see {doc}`share-a-run`.

To give the run itself, with its fields and its tables, instead of maps, see
{doc}`share-a-run`.

## What can go wrong

| Symptom | Cause | Fix |
|---|---|---|
| One `…_fields.nc` file instead of GeoTIFFs | Several dates and no `--format`, so the default is NetCDF | Add `--format geotiff` |
| `Name what to export (see --list), or write 'all'. Example: hmp export <run> head --time 2002-10-15`, exit 2 | No variable after the run name | Name the variables, as above |
| ``Reference 'x' not found. Run `hmp catalog ls` to list known runs.``, exit 10 | The name matches no run of the project | Check the name, and the folder you run from |
| The files are not in the folder you gave | A relative `--folder` is read from `share/`, and a relative `--file` from the folder | Give an absolute folder, or look in `share/<folder>/` |
| The raster shows values outside the catchment outline | The grid covers the catchment and its buffer: 21 406 cells, of which 11 488 are inside the catchment | Clip it with `watershed.gpkg` |
| The layers are on the wrong place in the GIS | The CRS of the project is not the one the colleague assumed | Pass `--crs EPSG:<code>` to the export, or tell them the CRS |
| The layers have no colours | No style is written | Style them in the GIS |

## Next

- Give a whole run: {doc}`share-a-run`.
- The exports of a run file, one block per kind: {doc}`export-results`.
- Every option of the command: {doc}`../reference/cli/export`.

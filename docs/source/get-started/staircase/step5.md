# Step 5: every export

```{hmp-task}
Task
: Write the results of step 4 in every format HydroModPy can export, and ask for more files once the run exists.

Time
: 1 to 2 min for the run, 1.5 to 3 min for the command.

Needs
: The example files ({doc}`index`). Nothing is downloaded.

Gives
: Eight figures and fourteen files, from GeoPackage to a portable archive of the run.
```

Step 5 does not change the model. It is step 4 with its results written out in every format
HydroModPy can export. The file drops the inherited exports with `export__delete = true`
and states its own list, one `[[export]]` block per request. A block says *what*
(`variables`), *when* (`time` or `period`), and where and how (`format`, `file`, `crs`).

```{image} /_static/figures/staircase/step5/watertable_depth_map.webp
:alt: Depth to the water table over the Nançon catchment on 15 October 2002, from 0 to 30 m.
:class: only-light
:width: 60%
:align: center
```

```{image} /_static/figures/staircase/step5/watertable_depth_map-dark.webp
:alt: Depth to the water table over the Nançon catchment on 15 October 2002, from 0 to 30 m.
:class: only-dark
:width: 60%
:align: center
```

The map is the field of one of the exports below, `watertable_depth_2002-10-15.tif`, drawn.

## The file

::::{tab-set}

:::{tab-item} The file
```{hmp-step} step5_export.toml
```
:::

:::{tab-item} Changed vs step 4
The resolved file of step 5 against the resolved file of step 4. The model is the same: the
changes are the figures and the export blocks.

```diff
--- step4_transient
+++ step5_export
@@ -7,3 +7,3 @@
 [simulation]
-name = "nancon_step4_transient"
+name = "nancon_step5_export"
 
@@ -76,7 +76,10 @@
 figures = [
+    "watershed_id_card",
     "flux_timeseries",
     "hydrograph_sim_obs",
+    "watertable_depth_map",
     "seepage_map",
+    "seepage_network_confusion_map",
+    "downslope_distance_map",
     "flow_persistence_map",
-    "flow_intermittence_map",
 ]
@@ -89,30 +92,2 @@
 cycle = "2002"
-
-[[export]]
-variables = "watershed"
-
-[[export]]
-variables = [
-    "watertable_depth",
-    "seepage_mask",
-]
-time = "last"
-
-[[export]]
-variables = "budget"
-
-[[export]]
-variables = "hydrographic_network_reference"
-
-[[export]]
-variables = [
-    "head",
-    "watertable_depth",
-]
-
-[[export]]
-variables = [
-    "discharge",
-    "discharge_obs",
-]
 
@@ -151 +126,62 @@
 ]
+
+[[export]]
+variables = [
+    "watershed",
+    "hydrographic_network_reference",
+]
+
+[[export]]
+variables = "watershed"
+format = "shapefile"
+
+[[export]]
+variables = "watershed_dem"
+
+[[export]]
+variables = [
+    "head",
+    "watertable_depth",
+    "seepage_mask",
+]
+time = "2002-10-15"
+
+[[export]]
+variables = "simulated_active_network"
+time = "2002-10-15"
+format = "geopackage"
+
+[[export]]
+variables = [
+    "head",
+    "watertable_depth",
+]
+file = "watertable_2000_2002.nc"
+
+[[export]]
+variables = [
+    "discharge",
+    "discharge_obs",
+]
+period = [
+    "2001-01-01",
+    "2002-12-31",
+]
+
+[[export]]
+variables = "budget"
+
+[[export]]
+variables = "watertable_depth"
+time = "2002-10-15"
+file = "watertable_depth_wgs84.tif"
+crs = "EPSG:4326"
+
+[[export]]
+variables = "head"
+time = "2002-10-15"
+format = "vtu"
+
+[[export]]
+variables = "all"
+format = "package"
```
:::

::::

## Run it

::::{tab-set}
:sync-group: api

:::{tab-item} Command line
:sync: cli

```bash
hmp run step5_export.toml
hmp export nancon_step5_export --list
```

`--list` prints what the run can export, by kind, and writes nothing.
:::

:::{tab-item} Python
:sync: python

```python
import hydromodpy as hmp

run = hmp.run("step5_export.toml")
```

Once the run exists, `hmp.export(run, ["head", "watertable_depth"], time="2002-10-15")`
writes more files and returns their paths.
:::

::::

## What you get

Eleven export blocks write fourteen files, in `share/nancon_step5_export/`. The format
follows the data unless the block says otherwise: a vector layer is a GeoPackage, a series
or a table is a CSV, and a field at one instant is a GeoTIFF.

| What | When | Format |
|---|---|---|
| the catchment and the mapped network | | GeoPackage |
| the catchment | | Shapefile |
| the DEM the catchment was cut from | | GeoTIFF |
| `head`, `watertable_depth`, `seepage_mask` | 15 October 2002 | one GeoTIFF per variable |
| the simulated active network, as mesh cells | 15 October 2002 | GeoPackage |
| `head`, `watertable_depth` | the whole record | NetCDF, `watertable_2000_2002.nc` |
| `discharge`, `discharge_obs` | 2001 and 2002 | CSV |
| the water budget, monthly | | CSV |
| `watertable_depth` | 15 October 2002 | GeoTIFF reprojected to `EPSG:4326`, for a web map |
| `head` | 15 October 2002 | VTU, for ParaView |
| everything | | a portable archive of the run (`package`) |

The Shapefile is one block and several files (`.shp`, `.dbf`, `.prj`, `.shx`, `.cpg`), which
the run counts as one export.

Eight figures, drawn from the same data: `watershed_id_card`, `flux_timeseries`,
`hydrograph_sim_obs`, `watertable_depth_map`, `seepage_map`, `seepage_network_confusion_map`,
`downslope_distance_map` and `flow_persistence_map`.

Once a run exists you can also ask for files without editing the TOML, for example
`hmp export nancon_step5_export head watertable_depth --time 2002-10-15`.

## Key fields

```{hmp-params}
export.variables
export.time
export.format
export.file
```

The other keys of a block are {toml}`export.period`, {toml}`export.crs` and
{toml}`export.folder`.

Next: {doc}`step6`, a daily run with a soil reservoir.

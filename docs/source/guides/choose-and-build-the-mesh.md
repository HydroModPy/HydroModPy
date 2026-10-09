# Choose and build the mesh

```{hmp-task}
Task
: Keep the structured grid cut from the DEM, or build a Gmsh mesh that follows the rivers and is finer where you need it.

Time
: Fifteen minutes. The file below meshes and runs in under a minute on two cores.

Needs
: A model that runs on MODFLOW 6, and for local refinement a vector file of the places to refine.

Gives
: A mesh whose cell count and shape you chose, and a map to check it.
```

The mesh is the set of cells the solver computes on. HydroModPy builds one of two kinds:
a structured grid that follows the pixels of the DEM, and a mesh of irregular cells built
by Gmsh. The structured grid needs no key at all. A Gmsh mesh follows the river traces,
the geological contacts or both, and takes a cell size that can change from place to place.

The worked case is example 04. Its files run on the structured grid of 21 406 cells of
75 m. The blocks below are merged onto `step1_minimal.toml`. The file of this guide meshes
the Nançon catchment with Gmsh, along the river network, and refines the mesh around the
pumping well of {doc}`add-wells`.

{download}`Download the file of this guide <recipes/model/guide_mesh.toml>` and
{download}`the refinement point <recipes/model/well_w1.geojson>`. Save both in the folder of
example 04.

## What you need first

- A model that runs on MODFLOW 6. MODFLOW-NWT builds its own structured grid and ignores
  a Gmsh mesh. The Boussinesq solver needs one: see {doc}`choose-a-solver`.
- For a mesh that follows the rivers, the river network extracted from the DEM. Step 2
  switches it on.
- For a mesh that follows the geology, a geology polygon layer.
- For local refinement, a vector file (GeoPackage, Shapefile or GeoJSON) of the points,
  lines or polygons to refine around.

## 1. Keep the structured grid, or resample it

Without a mesh section, the model runs on the DEM grid of the catchment: one cell per
pixel. {toml}`modflow6.sgrid.planar.mode` keeps that grid (`keep_native`) or resamples the
DEM to a number of rows and columns you give (`resample_to_shape`). A coarser shape is a
quick way to a lighter model.

```toml
base_config = "step1_minimal.toml"

[modflow6.sgrid.planar]
mode = "resample_to_shape"
nx = 70
ny = 77
```

```{hmp-params}
modflow6.sgrid.planar.mode
modflow6.sgrid.planar.nx
modflow6.sgrid.planar.ny
```

MODFLOW 6 writes every grid as a DISV grid, structured or not.

## 2. Build a Gmsh mesh along the rivers

Add a `[mesh_catchment]` section. {toml}`mesh_catchment.constraints_mode` is required and
has no default. It says which lines the cell edges must follow:

| `constraints_mode` | The edges follow | You also need |
|---|---|---|
| `rivers_only` | the river traces | the river network of `[geographic.river_network]` |
| `geology_only` | the geological contacts | a `[mesh_catchment.geology]` section |
| `geology_rivers` | both | both |

Example 04 has no geology layer, so its mesh follows the rivers only. The rivers are the
network HydroModPy extracts from the DEM, so its threshold sets how many rivers the mesh
follows.

```toml
base_config = "step1_minimal.toml"

[simulation]
name = "nancon_guide_mesh"

[geographic.river_network]
enabled = true
threshold_mode = "area_km2"
threshold_area_km2 = 0.5

[mesh_catchment]
constraints_mode = "rivers_only"
cache = true
```

```{hmp-params}
mesh_catchment.constraints_mode
mesh_catchment.rivers.source
geographic.river_network.threshold_area_km2
```

The rivers come from the generated network, never from an observed one: the mesh is a
model input, and observed data is not.

Gmsh does not give the same mesh twice: it reseeds from the clock, so two runs of one file
give two meshes and two sets of results. {toml}`mesh_catchment.cache` keeps the first mesh
and reuses it while its inputs stay the same. Turn it on for any run you will compare or
calibrate.

```{hmp-params}
mesh_catchment.cache
```

## 3. Size the cells

{toml}`mesh_catchment.zone_meshing.global_size` is the target size of a cell, in metres,
over the whole domain. It is 250 m by default. {toml}`min_size|mesh_catchment.zone_meshing.min_size`
and {toml}`max_size|mesh_catchment.zone_meshing.max_size` bound the size where it varies.
With {toml}`refine_interfaces|mesh_catchment.zone_meshing.refine_interfaces`, the cells
get smaller near the rivers or the contacts the mesh follows.

```toml
base_config = "step1_minimal.toml"

[geographic.river_network]
enabled = true
threshold_mode = "area_km2"
threshold_area_km2 = 0.5

[mesh_catchment]
constraints_mode = "rivers_only"
cache = true

[mesh_catchment.zone_meshing]
global_size = 200.0
```

```{hmp-params}
mesh_catchment.zone_meshing.global_size
mesh_catchment.zone_meshing.min_size
mesh_catchment.zone_meshing.max_size
mesh_catchment.zone_meshing.refine_interfaces
```

The number of cells grows as the inverse square of the size. How many cells a size costs,
and how the dual of the triangulation halves that count, is in {doc}`../theory/mesh`.

## 4. Refine where it matters

A `[[mesh_catchment.refinement_zone]]` entry names a vector file and a cell size. A polygon
is refined inside. A point or a line is widened into a corridor of half-width `buffer`,
over which the size also returns to the background size. Several entries make several
zones.

```toml
base_config = "step1_minimal.toml"

[geographic.river_network]
enabled = true
threshold_mode = "area_km2"
threshold_area_km2 = 0.5

[mesh_catchment]
constraints_mode = "rivers_only"
cache = true

[[mesh_catchment.refinement_zone]]
path = "well_w1.geojson"
cell_size = 30.0
buffer = 600.0
```

```{hmp-params}
mesh_catchment.refinement_zone.path
mesh_catchment.refinement_zone.cell_size
mesh_catchment.refinement_zone.buffer
```

A bare file name is looked for in the `data/refinement_zone/` folder of the workspace,
then in the data folder, then next to the config file. The file is reprojected to the
project CRS when it carries a CRS; a file without one is taken as already in the project
CRS. Around a lake, {toml}`mesh_catchment.lake_refinement` does the same job for the
shoreline and the dam.

## 5. Run it and look at the mesh

::::{tab-set}

:::{tab-item} Command line
```bash
hmp run guide_mesh.toml
hmp viz show @last mesh_map
```
:::

:::{tab-item} Python
```python
import hydromodpy as hmp

run = hmp.run("guide_mesh.toml")
print(run.n_cells)
hmp.figure(run, "mesh_map")
```
:::

::::

`mesh_map` draws every cell, coloured by the ground elevation, and gives the cell count in
its title: 4 770 cells, against 21 406 on the structured grid of step 1. The cells are
finer along the valleys and around the well:

```{figure} /_static/figures/guides/choose-and-build-the-mesh/mesh_map.webp
:alt: Gmsh mesh of the Nançon catchment, with Voronoi cells coloured by elevation, finer along the rivers and around one point.

`mesh_map` of the file of this guide.
```

## 6. Choose what a cell is

Three settings act on the cells of a Gmsh mesh under MODFLOW 6.

- {toml}`modflow6.sgrid.grid_dual` is `voronoi` by default: the solver computes on the
  Voronoi dual of the triangulation, with about half as many cells, whose faces are
  perpendicular to the lines between cell centres. `triangle` keeps the triangles.
- {toml}`modflow6.sgrid.top_sampling.mode` reads the top of a cell at its centre
  (`centroid`, the default) or from every DEM pixel inside it (`zonal`), with the lowest
  pixel on a channel. See the section on the top of a cell in {doc}`../theory/mesh`.
- {toml}`modflow6.runtime.mf6_enable_xt3d` adds the XT3D terms, which correct the flow
  between cells whose faces are not perpendicular to the line between their centres. Left
  unset, HydroModPy turns them on only for a mesh far from orthogonal or an anisotropic K.
  The reason is in {doc}`../theory/solvers/xt3d-on-irregular-disv-meshes`.

```{hmp-params}
modflow6.sgrid.grid_dual
modflow6.sgrid.top_sampling.mode
modflow6.runtime.mf6_enable_xt3d
```

## 7. Use a mesh you already have

A mesh built elsewhere is declared under `[mesh_input]`, by its `.msh` file or by the
solver bundle HydroModPy wrote beside a mesh. `[mesh_input]` and `[mesh_catchment]`
exclude each other.

```{hmp-params}
mesh_input.mesh_path
mesh_input.bundle_dir
```

The full list of mesh keys is in {doc}`../reference/parameters/mesh_catchment` and
{doc}`../reference/parameters/mesh_input`.

## Check that it worked

1. `hmp config check` refuses a `[mesh_catchment]` without
   {toml}`mesh_catchment.constraints_mode`, and a refinement zone whose `buffer` is
   smaller than its `cell_size`.
2. The title of `mesh_map` gives the cell count. Compare it with the count you aimed at
   before you run anything long.
3. Run the file twice with `cache = true`: the second run reuses the mesh and the
   results do not move.

## What can go wrong

| Symptom | Cause | Fix |
|---|---|---|
| `constraints_mode is required.` | A `[mesh_catchment]` section without {toml}`mesh_catchment.constraints_mode`. | Write one of the three values of step 2. |
| `geology section is required when constraints_mode includes geology.` | `geology_only` or `geology_rivers` without `[mesh_catchment.geology]`. | Declare the geology, or take `rivers_only`. |
| `threshold_area_km2 must be > 0 when threshold_mode='area_km2'.` at the `build_geographic` step | A mesh along the rivers with no river network threshold. | Write `[geographic.river_network]` with a threshold, as in step 2. |
| `buffer must be >= cell_size: a corridor thinner than one target cell slips between the size-field sampling nodes and silently meshes at the background size.` | A refinement zone whose corridor is thinner than one cell. | Raise `buffer`, or leave it out: it is then twice `cell_size`. |
| `refinement zone '<path>' has no usable geometry.` | The zone file is empty, or holds only empty geometries. | Check the file. |
| `refinement zone '<path>' has no CRS; assuming it is already in the project CRS.` (warning) | The zone file has no CRS. | Write the CRS in the file, or make sure the coordinates are in the project CRS. |
| `Embedded [mesh_catchment] and external [mesh_input] are mutually exclusive. Use only one mesh source.` | Both sections in one file. | Keep one. |
| Two runs of one file give different heads | Gmsh gave two meshes. | Set {toml}`mesh_catchment.cache` to `true`. |
| A well on the mesh is refused with `[lay, row, col] addressing needs a structured grid` | A well placed by cell index on a Gmsh mesh. | Place it by coordinates: see {doc}`add-wells`. |

## Where to go next

- How the mesh is built, and what its cells cost: {doc}`../theory/mesh`.
- Which solver takes which mesh: {doc}`choose-a-solver`.
- The vertical layers of the mesh: {doc}`depth-and-substratum`.
- Every mesh key: {doc}`../reference/parameters/mesh_catchment`.

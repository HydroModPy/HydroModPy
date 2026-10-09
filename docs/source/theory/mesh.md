# The mesh

The solver does not see the DEM. It sees cells, and one top elevation, one bottom
elevation and one centre for each of them. This page gives the rules that turn the
DEM into those cells: how the cells are laid out, how the top of a cell is read from
the DEM, how many cells a given size costs, and which checks the code runs on the
result.

:::{note}
**Scope.** The cell layout below is the one of MODFLOW 6, which reads every grid as a
DISV grid. MODFLOW-NWT builds a structured grid only and ignores a runtime mesh.
Boussinesq uses the triangles of the Gmsh mesh as its cells, so the Voronoi dual of
{ref}`mesh-voronoi` does not apply to it, and it ignores the top sampling of
{ref}`mesh-top`. What the solver does with the cells is on {doc}`solvers`.
The extra terms XT3D adds on a non-orthogonal mesh are on
{doc}`solvers/xt3d-on-irregular-disv-meshes`. To set up a mesh, see
{doc}`../reference/parameters/mesh_catchment`.
:::

## The chain in one list

The code builds the cells in this order. Each step is a section below.

1. Two surfaces: the top from the DEM $Z$ and the bottom from the depth model.
2. A planar support, from one of two sources: the pixels of the DEM (a structured
   grid, {ref}`mesh-structured`), or a Gmsh triangulation built at run time
   ({ref}`mesh-gmsh`), which MODFLOW 6 turns into its Voronoi dual by default
   ({ref}`mesh-voronoi`).
3. One top elevation per cell ({ref}`mesh-top`) and one bottom elevation per cell.
4. A check of the thickness ({ref}`mesh-acceptance`), then the layers
   ({ref}`mesh-layers`).
5. The export to MODFLOW 6 as a DISV grid. The cells that have no valid top or bottom
   are written inactive.

Example 04 uses the first source: its files declare neither a `[mesh_catchment]` section
nor a `[modflow6.sgrid]` section, so every cell is one DEM pixel. The header of
`step1_minimal.toml` counts 21406 cells of 75 m for this domain.

::::{dropdown} Notation of this page
```{hmp-notation}
```
::::

(mesh-structured)=
## 1. A structured grid

With {toml}`modflow6.sgrid.planar.mode` at its default, the cells are the pixels of the
top raster, with the same size and the same extent. A cell $(i,j)$ takes the value of
pixel $(i,j)$, with no interpolation:

$$
z_{\mathrm{top},ij} = Z_{ij}, \qquad N_S = n_{\mathrm{row}}\, n_{\mathrm{col}}, \qquad
a_{ij} = \Delta_x \Delta_y .
$$

A pixel that is nodata makes the cell inactive. The cell still exists in the grid, so
$N_S$ counts the active and the inactive cells.

With {toml}`modflow6.sgrid.planar.mode` set to resample the grid to a shape, top and
bottom are resampled to $n_{\mathrm{row}} \times n_{\mathrm{col}}$ cells over the same
extent, with the rule of {toml}`modflow6.sgrid.planar.resampling`
(`project_surfaces_to_planar_grid`). If a cell then covers at least two DEM pixels, the
top of the cell is the zonal statistic of {ref}`mesh-top` instead of the
resampled value (`_cells_cover_pixels`, `_zonal_structured_top`). A grid whose cells are
the pixels is never touched by the zonal top.

MODFLOW 6 reads this grid as a DISV grid. MODFLOW-NWT reads it as a DIS grid.

(mesh-gmsh)=
## 2. A runtime mesh from Gmsh

A `[mesh_catchment]` section makes the run build a triangulation of $\Omega$ with Gmsh
before the solver is prepared (`run_mesh_phase`). The project refuses a file that has both a
`[mesh_catchment]` and a `[mesh_input]` section (`Embedded [mesh_catchment] and external [mesh_input] are mutually`):
they are two sources for the same mesh. A mesh that already exists is declared with
{toml}`mesh_input.mesh_path` or {toml}`mesh_input.bundle_dir` instead, and goes through
the steps below like a mesh the run built.

The triangle sizes come from a size field. Around the interface curves (rivers,
geology interfaces, the watershed boundary), when
{toml}`mesh_catchment.zone_meshing.refine_interfaces` is on, the code gives Gmsh a
Distance field to the curves and a Threshold field on it, with the lower distance set to
zero. With $\xi$ the distance to the nearest interface, the wanted size is linear
between the two limits:

$$
\ell_0(\xi) = \ell_s + (\ell_g - \ell_s)\,\min\!\left(1, \frac{\xi}{\xi_s}\right).
$$ (eq-mesh-size)

When the refinement policy is on, there is one such field per family of curves, with its
own $\ell_s$ and $\xi_s$, and Gmsh takes the smallest size of all the fields
(`apply_family_refinement_fields`). The size actually used is bounded by Gmsh options
the code sets from the three keys of the section (`apply_mesh_options`):

$$
\ell(\mathbf{x}) = \min\!\bigl(\ell_{\max}',\ \max(\ell_{\min}',\ \ell_0(\mathbf{x}))\bigr),
\qquad
\ell_{\min}' = \begin{cases}\ell_{\min} & \text{if set,}\\ \ell_g & \text{otherwise,}\end{cases}
\qquad
\ell_{\max}' = \begin{cases}\ell_{\max} & \text{if set,}\\ \ell_g & \text{otherwise.}\end{cases}
$$ (eq-mesh-size-bounds)

The size fields of the lakes, of the refinement zones and of the coarsening outside the
watershed are combined with the interface fields by the minimum
(`set_background_mesh_from_fields`). The upper bound is raised to the largest size of such
a regional field when the section declares one (`compute_effective_max_size`). The
lower bound has a consequence that the keys do not announce: with no
{toml}`mesh_catchment.zone_meshing.min_size`, $\ell_{\min}' = \ell_g$, and every size
below $\ell_g$ is raised back to $\ell_g$. An {toml}`interface_size\|mesh_catchment.zone_meshing.interface_size`
below the background size then changes nothing ({ref}`mesh-limits`). In the code:
`apply_mesh_options`.

The 2D algorithm is the one named by {toml}`mesh_catchment.zone_meshing.algorithm`. The
code knows four names and maps them to the Gmsh codes. Gmsh does not give the same triangulation twice for the same input.
{toml}`mesh_catchment.cache` keeps the first one and reuses it while the inputs that
shape the mesh are unchanged.

(mesh-voronoi)=
## 3. The Voronoi dual

MODFLOW 6 does not take the triangles as cells by default. With
{toml}`modflow6.sgrid.grid_dual` at its default, the code takes the vertices of the
triangulation as seeds $\mathbf{s}_i$ and builds the Voronoi (PEBI) cell of each seed,
clipped to the outline of the triangulation:

$$
\mathcal{V}_i = \bigl\{\mathbf{x} \in \Omega :
\lVert \mathbf{x} - \mathbf{s}_i \rVert \le \lVert \mathbf{x} - \mathbf{s}_j \rVert
\ \ \forall j \bigr\}.
$$

The cell centre written to the DISV file is the seed itself. Three rules complete the
construction:

- A seed whose cell falls entirely outside $\Omega$ is dropped.
- When the clip splits a cell, the piece that contains the seed is kept.
- If no piece contains the seed, the largest piece is kept and its representative point
  becomes the centre.

The outline $\Omega$ is rebuilt from the edges that belong to exactly one triangle. The
coordinates of the vertices are rounded to 1 mm so
that the corners shared by two cells are one vertex, which assumes a projected CRS in
metres.

Three consequences follow.

**The number of cells.** A triangulation of a region without holes has $n_v$ vertices,
$n_b$ of them on its outline, and $N_T$ triangles with

$$
N_T = 2 n_v - n_b - 2 .
$$ (eq-euler-count)

The dual has one cell per seed, so $N_V = n_v$ and $N_V \approx N_T / 2$ when $n_b$ is
small against $n_v$.

**The faces.** The face between two cells is the perpendicular bisector of the segment
between their seeds. The faces are not the edges of the triangulation. A river that was
a chain of triangle edges runs through the middle of a chain of Voronoi cells: it is no
longer the boundary of any cell.

**The orthogonality.** The line between the two centres is perpendicular to the face, so
$\varphi_{nm} = 0$ on every connection whose two cells kept their seed as centre.
{ref}`mesh-angle` says why this matters. In the code: `voronoi_dual_of_mesh`.

With {toml}`modflow6.sgrid.grid_dual` set to `"triangle"`, the triangles are the cells
and the centre of a cell is the mean of its three vertices.

(mesh-angle)=
## 4. Flow between two cells, and the angle

MODFLOW 6 writes the flow from cell $n$ to a neighbour $m$ with the two-point form of the
control-volume finite difference method {cite:p}`harbaugh2005,langevin2017`, the term
$G_{nm}\,(h_m - h_n)$ of {eq}`eq-cell-balance`. The conductance $G_{nm}$ is built from the conductivity of the two cells, the
length of their shared face and the distance between their centres. The form is exact
when the conductivity is isotropic in the plane and the line between the centres is
perpendicular to the face. HydroModPy measures the departure from that condition on
every connection, as an angle. With $\mathbf{d}_{nm}$ the vector between the two centres
and $\mathbf{n}_{nm}$ the unit normal of the shared edge:

$$
\varphi_{nm} = \arccos\!\left(\frac{\lvert \mathbf{d}_{nm} \cdot \mathbf{n}_{nm} \rvert}
{\lVert \mathbf{d}_{nm} \rVert}\right).
$$ (eq-nonorthogonality)

Only an edge shared by exactly two cells counts as a connection. The summary the code
keeps is the median, the 95th and 99th percentiles, the maximum and the share of
connections above 30 degrees. What the angle does to the flux, and when the code turns
on the XT3D option that corrects it, is on {doc}`solvers/xt3d-on-irregular-disv-meshes`.
In the code: `connection_nonorthogonality_deg`.

**Two triangles.** Cut a $2 \times 1$ rectangle along its diagonal. The shared edge goes
from $(2,0)$ to $(0,1)$, with a normal along $(1,2)$. The centres are the vertex means,
$(2/3, 1/3)$ and $(4/3, 2/3)$, so $\mathbf{d} = (2/3, 1/3)$ and

$$
\cos\varphi = \frac{\lvert (2,1)\cdot(1,2) \rvert}{\sqrt5\,\sqrt5} = \frac{4}{5},
\qquad \varphi \approx 36.9^\circ .
$$

**The same corners, as seeds.** The four corners of the rectangle, taken as seeds, give
four cells of $1 \times 0.5$ with four connections, all at $0^\circ$. Both results were
checked with `connection_nonorthogonality_deg`, and the four cells with
`voronoi_planar_mesh`.

(mesh-top)=
## 5. The top of a cell

The top of a cell is one number, read from the DEM $Z$. Two rules exist, set by
{toml}`modflow6.sgrid.top_sampling.mode`. The bottom is always read by the first rule.

### Centroid

The DEM is sampled at the centre of the cell with a bilinear interpolation between the
four pixel centres around it. The weights $w_k$ are the
bilinear ones, and a nodata pixel gets a weight of zero before the sum is normalised:

$$
\tilde z_c = \frac{\sum_{k=1}^{4} w_k\, Z_k\, \mathbf{1}[Z_k \text{ valid}]}
{\sum_{k=1}^{4} w_k\, \mathbf{1}[Z_k \text{ valid}]} .
$$

The result is undefined, and the cell inactive, when the centre is outside the raster or
the four pixels are nodata. On an incised channel the centre of a
cell often falls on a bank, not on the thalweg, and the cell is then too high.

### Zonal

The zonal rule reduces every pixel whose centre falls in the cell. A pixel belongs to the cell that contains
its centre: for a mesh, the code burns each cell polygon into a raster of the DEM; for a
structured grid, it computes the row and column by arithmetic. A pixel is channel when the stream raster of the
delineation says so, with the mask widened by
{toml}`modflow6.sgrid.top_sampling.channel_buffer_px` pixels. The raster is read only when
{toml}`modflow6.sgrid.top_sampling.channel_source` asks for it.
Without a stream raster, every pixel is a hillslope pixel.

With $\operatorname{stat}$ the statistic named by
{toml}`modflow6.sgrid.top_sampling.channel_stat` on the channel pixels, and by
{toml}`modflow6.sgrid.top_sampling.hillslope_stat` on the others (`mean`, `median`,
`min`, `max`, and the 10th and 25th percentiles):

$$
z_{\mathrm{top},c} =
\begin{cases}
\operatorname{stat}_{\mathrm{ch}}\{Z_p : p \in P_c^{\mathrm{ch}}\}
  & P_c^{\mathrm{ch}} \neq \emptyset, \\[0.5ex]
\operatorname{stat}_{\mathrm{hill}}\{Z_p : p \in P_c\}
  & P_c^{\mathrm{ch}} = \emptyset \text{ and } \lvert P_c \rvert \ge n_{\min}, \\[0.5ex]
\tilde z_c & \text{otherwise.}
\end{cases}
$$ (eq-zonal-top)

A channel cell needs one channel pixel. A hillslope cell needs $n_{\min}$ pixels, and a
cell finer than the DEM falls back to the centroid value. Two corrections follow, in this
order:

$$
\text{if } \lvert z_{\mathrm{top},c} - \tilde z_c \rvert > \varepsilon_z
\text{ on a hillslope cell:}\quad z_{\mathrm{top},c} \leftarrow \tilde z_c,
$$

$$
z_{\mathrm{top},c} \leftarrow \max\bigl(z_{\mathrm{top},c},\ z_{\mathrm{bot},c} + b_{\min}\bigr)
\quad \text{on every active cell.}
$$

The first one guards against a nodata edge: channel cells are exempt, since they are
lowered on purpose. It is off when $\varepsilon_z = 0$. The second one keeps a lowered top
above the bottom. Only the top is zonal; the bottom keeps its centroid value, so a
lowered top thins every layer of that column. The code logs, once per build, how many cells
took a zonal value, how many are channel cells, and how far the tops were lowered.

The zonal rule falls back to the centroid value, with a message in the log, in three
cases: a surface with no georeferencing (`Zonal top sampling needs a georeferenced surface; using centroid sample.`),
a channel source with no stream raster (`Zonal channel_source=%s but no stream raster found`;
the channel class is then off), and a structured grid whose cells cover fewer than two DEM
pixels (`Zonal top sampling skipped: a grid cell`). In the code: `zonal_top`.

(mesh-layers)=
## 6. Thickness and layers

The column of each cell is cut into layers by shares of its thickness, the same shares in
every cell, set by {toml}`modflow6.sgrid.vertical.genmtd_lay`. The rule,
{eq}`eq-layer-bottom`, and its three strategies are on {ref}`gwf-layers`.

Every layer shares the cells of the plan: the mesh is a vertical extrusion. A cell is inactive in every layer when its top or its bottom is nodata,
not finite, or at or below the nodata value.

(mesh-budget)=
## 7. How many cells a size costs

The cost of a run grows with the number of cells, so the sizes of a structured grid and
of a mesh are compared at equal cell count. The ideal count below assumes cells of one
uniform size over an area $A_\Omega$.

For a structured grid of pixel side $\Delta$:

$$
N_S = \frac{A_\Omega}{\Delta^2}.
$$

For a triangulation of equilateral triangles of side $\ell$, the triangle area is
$\frac{\sqrt3}{4}\ell^2$. The Voronoi cells are hexagons, whose area is
$\frac{\sqrt3}{2}\ell^2$ when two neighbouring seeds are $\ell$ apart:

$$
N_T = \frac{4}{\sqrt3}\,\frac{A_\Omega}{\ell^2} \approx 2.31\,\frac{A_\Omega}{\ell^2},
\qquad
N_V = \frac{2}{\sqrt3}\,\frac{A_\Omega}{\ell^2} \approx 1.15\,\frac{A_\Omega}{\ell^2}.
$$ (eq-cell-count)

Equal counts then give the edge length that costs the same as a grid of side $\Delta$:

| Cells | Count for an area $A_\Omega$ | Edge length at the cost of the grid of side $\Delta$ |
|---|---|---|
| Square pixels | $A_\Omega/\Delta^2$ | $\Delta$ |
| Voronoi cells | $\approx 1.15\,A_\Omega/\ell^2$ | $\ell = \Delta \sqrt{2/\sqrt3} \approx 1.07\,\Delta$ |
| Triangles | $\approx 2.31\,A_\Omega/\ell^2$ | $\ell = \Delta \sqrt{4/\sqrt3} \approx 1.52\,\Delta$ |

**Worked example.** The 21406 cells of 75 m of the header of `step1_minimal.toml` (the file does not say if
the count includes the inactive cells) cover
$21406 \times 75^2\ \mathrm{m^2} \approx 120\ \mathrm{km^2}$. The same count on a
Voronoi mesh means seeds about $81\ \mathrm{m}$ apart; on a triangle mesh it means
triangles of about $114\ \mathrm{m}$ side. These are ideal figures. A real mesh refines
near the interfaces, so its count is the integral of $1/\ell(\mathbf{x})^2$ over the
domain, and the count of a run is the number of cells ($\mathrm{ncpl}$) of its DISV
file.

**Worked example of the vertex count.** Take 36 seeds on a $6 \times 6$ lattice, the 16
inner ones moved at random, $n_b = 20$ of them on the outline. The Delaunay triangulation
has $N_T = 2 \cdot 36 - 20 - 2 = 50$ triangles and the dual has 36 cells. Running
`voronoi_dual_of_mesh` on that triangulation returns 36 cells, with a
non-orthogonality of $0^\circ$ on every connection.

$N_S$ counts the cells of the whole raster box, active or not ({ref}`mesh-structured`). The count of a
mesh is its number of cells, and every cell of a mesh lies in $\Omega$.

(mesh-acceptance)=
## 8. The checks the code applies

The code does not compute a minimum angle, an aspect ratio, a skewness or a ratio of the
areas of two neighbours, and it refuses no mesh for its shape. The table lists what it
does check. Where a limit is a number, the table names the constant that holds it.

| What is checked | Rule | What happens | Where |
|---|---|---|---|
| Top and bottom overlap | at least one cell where both are valid | refused: `No finite overlapping valid cells found between top and bottom surfaces.` | `_assert_bottom_below_top` in `discretization_spatial.py`, and the same check in `sgrid_generation.py` |
| Bottom below top | strictly, on every valid cell | refused: `Bottom surface must be strictly below top surface on valid cells` | the same two functions |
| Cells much thicker than the rest | thickness above the larger of 10 times the median and 500 m | warning only, runtime mesh only: `Aquifer thickness outliers:` | `_warn_on_outlier_thickness`; constants `_THICKNESS_OUTLIER_FACTOR` and `_THICKNESS_OUTLIER_FLOOR_M` in `discretization_spatial.py` |
| Non-orthogonality | the trigger of {doc}`solvers/xt3d-on-irregular-disv-meshes` | XT3D switched on, not a refusal | `resolve_xt3d_decision` |
| Zonal top | $n_{\min}$ pixels, $\varepsilon_z$, $b_{\min}$ | fallback or clamp, counted in the log | `zonal_top` in `zonal_stats.py`; the keys are on the cards below |
| Structured grid for the zonal top | each cell covers at least two DEM pixels | zonal top skipped, resampled top kept | `_cells_cover_pixels` (argument `min_pixels`) |
| Size keys of the mesher | $\ell_s \leq \ell_g$, $\ell_{\min} \leq \ell_{\max}$ | refused when the file is read: `interface_size must be <= global_size when refine_interfaces=true`, `min_size must be <= max_size` | `ZoneMeshingSettings` in `zone_meshing/config.py` |
| Geology | a geology section when the mode asks for geology | refused: `geology section is required when constraints_mode includes geology.` | `MeshCatchmentConfig` in `mesh/config/main.py` |
| Zones that overlap | priorities must settle every overlap | refused: `Overlapping zones detected without priority resolution` | `resolve_zone_overlaps` in `_polygon_cleaning.py` |
| Gap between the zones and the domain | the uncovered area is below a tolerance, and the constraint curves exist | recorded in the summary file of the mesh (`qa_checks`, `constraints_qa`), never enforced | `ZoneConformalQaChecks` in `_summary_sidecar.py`, `_build_constraints_qa_contract` in `reporting.py` |

The last row matters for the reading of a mesh: the summary file says whether the
constraints were embedded, and no code of `hydromodpy` reads that verdict. A mesh whose
summary says `overall_pass: false` still runs.

## Assumptions

- A cell has one top and one bottom. The surface inside the cell is flat.
- The mesh is a vertical extrusion of the plan: all layers share the cells of the plan.
- A mesh is fixed for the run. It does not move with the water table.
- The conductivity is isotropic in the plane. The code writes no input for horizontal
  anisotropy.
- The coordinates are in a projected CRS in metres. The merge of the vertices of the dual
  (1 mm) and every size of the mesher read this.
- The zonal rule treats a channel pixel as a pixel of the stream raster of the
  delineation. It does not read the observed network.

(mesh-limits)=
## Limits

- **No refinement without `min_size`.** With {toml}`mesh_catchment.zone_meshing.refine_interfaces`
  on and {toml}`mesh_catchment.zone_meshing.min_size` unset, the lower bound of the size is
  $\ell_g$, and Gmsh raises every size to it. In a test with Gmsh 4.15.2, on a
  $1000\ \mathrm{m}$ square with a Distance and a Threshold field on one side
  ($\ell_s = 20$ m, $\ell_g = 100$ m, $\xi_s = 300$ m, the two bounds set as in
  {eq}`eq-mesh-size-bounds`), the mesh
  had 250 triangles with the lower bound at $\ell_g$ and 602 with it at 20 m. Set
  `min_size` at or below `interface_size`.

```toml
base_config = "step4_transient.toml"

# The lower bound of the size is set, so the refinement acts.
[mesh_catchment]
constraints_mode = "rivers_only"

[mesh_catchment.zone_meshing]
global_size = 300.0
min_size = 100.0
refine_interfaces = true
interface_size = 100.0
interface_distance = 600.0
```

- **The dual does not follow the constraints.** It keeps the outline of the domain, not
  the river traces or the geology interfaces. A cell can hold both sides of an interface.
- **A mesh bundle written for the triangles does not fit the dual.** The bundle holds one
  conductivity per triangle, and the dual has about half as many cells. The code then
  logs a warning that ends with `Configure K in [flow] or set grid_dual='triangle' to reuse the bundle.`
  and ignores the bundle value.
- **No shape check.** A sliver, an abrupt change of size or a high non-orthogonality does
  not stop a run. The non-orthogonality is the only shape measure the code reads, and it
  decides about XT3D, not about the mesh. `connection_nonorthogonality_deg` and
  `nonorthogonality_summary` can be called on any planar `HydroMesh` for a closer look.
- **MODFLOW-NWT is structured.** It ignores a runtime mesh, and its zonal top needs
  {toml}`modflownwt.sgrid.top_sampling.channel_source` at `"none"`: the file is refused
  otherwise.
- **Boussinesq ignores `grid_dual` and the top sampling.** It works on the triangles.
- **Not a 3D mesh.** The layers are an extrusion. A mesh whose footprint changes from one
  layer to the next, or that is refined in depth, is not represented.
- **Gmsh is not reproducible.** Two builds of the same input give two meshes, with
  different cell counts. {toml}`mesh_catchment.cache` pins the first one.
- **An outlier thickness only warns.** A raster nodata value read as an elevation gives a
  cell that is kilometres deep, with a clean top. The run converges. The warning is the
  only sign, and a structured grid does not emit it.

A structured grid can be coarser than the DEM to cut the cost. A resample would raise the
incised cells, and the zonal top restores them. A file that asks for both:

```toml
base_config = "step4_transient.toml"

# Cells coarser than the DEM pixels, with a top reduced from every pixel inside.
[modflow6.sgrid.planar]
mode = "resample_to_shape"
nx = 80
ny = 80

[modflow6.sgrid.top_sampling]
mode = "zonal"
channel_stat = "min"
hillslope_stat = "median"
```

A runtime mesh with the triangles kept as cells, for a run that compares the two layouts:

```toml
base_config = "step4_transient.toml"

[mesh_catchment]
constraints_mode = "rivers_only"

[modflow6.sgrid]
grid_dual = "triangle"
```

## Parameters of this page

The keys that choose the layout, the size and the top. The cards show the defaults and the
allowed values. The three keys of `[mesh_catchment.zone_meshing]` that bound the size are
in the first group.

```{hmp-params}
mesh_catchment.constraints_mode
mesh_catchment.cache
mesh_catchment.zone_meshing.algorithm
mesh_catchment.zone_meshing.global_size
mesh_catchment.zone_meshing.min_size
mesh_catchment.zone_meshing.max_size
mesh_catchment.zone_meshing.refine_interfaces
mesh_catchment.zone_meshing.interface_size
mesh_catchment.zone_meshing.interface_distance
mesh_input.mesh_path
mesh_input.bundle_dir
modflow6.sgrid.planar.mode
modflow6.sgrid.planar.nx
modflow6.sgrid.planar.ny
modflow6.sgrid.planar.resampling
modflow6.sgrid.grid_dual
modflow6.sgrid.top_sampling.mode
modflow6.sgrid.top_sampling.hillslope_stat
modflow6.sgrid.top_sampling.channel_stat
modflow6.sgrid.top_sampling.channel_source
modflow6.sgrid.top_sampling.channel_buffer_px
modflow6.sgrid.top_sampling.spike_guard_tol_m
modflow6.sgrid.top_sampling.min_pixels
modflow6.sgrid.top_sampling.min_thickness_m
modflow6.sgrid.vertical.genmtd_lay
modflow6.sgrid.vertical.nlay
modflow6.sgrid.vertical.lay_decay
modflow6.sgrid.vertical.lay_proportions
modflow6.runtime.mf6_enable_xt3d
```

## Checked by

The tests that import the code of this page. The box is generated: a new test appears
here on the next build.

```{hmp-tested-by}
hydromodpy.spatial.mesh.ops.voronoi
hydromodpy.spatial.mesh.ops.zonal_stats
hydromodpy.spatial.mesh.ops.mesh_orthogonality
hydromodpy.spatial.mesh.cartesian_grid.sgrid_generation
hydromodpy.spatial.mesh.cartesian_grid.sgrid_config
hydromodpy.spatial.mesh.gmsh_grid.zone_meshing
hydromodpy.spatial.mesh.mesh_cache
hydromodpy.solver.modflow_grid.discretization_spatial
hydromodpy.solver.modflow6.builders.solver_options
```

## In the code

| What | Where |
|---|---|
| The surfaces, the plan, the top, the layers | `hydromodpy/solver/modflow_grid/discretization_spatial.py` (`build_spatial_discretization`, `resolve_domain_surfaces`, `project_surfaces_to_planar_grid`, `_build_extruded_solver_mesh_from_runtime_planar`, `_compute_layer_proportions`) |
| The structured grid | `hydromodpy/spatial/mesh/cartesian_grid/sgrid_generation.py` (`StructuredGridBuilder.build_from_surfaces`) |
| The keys of the grid | `hydromodpy/spatial/mesh/cartesian_grid/sgrid_config.py` |
| The centroid sample | `hydromodpy/spatial/surface_sampling.py` (`PreparedSurfaceSampler.sample`) |
| The zonal top | `hydromodpy/spatial/mesh/ops/zonal_stats.py` (`zonal_top`), `discretization_spatial.py` (`_zonal_top_flat`, `_zonal_structured_top`) |
| The channel mask | `hydromodpy/solver/modflow6/build.py` (`_resolve_channel_mask_for_zonal`) |
| The Voronoi dual | `hydromodpy/spatial/mesh/ops/voronoi.py` (`voronoi_dual_of_mesh`, `voronoi_cells`, `domain_polygon_from_mesh`) |
| The angle of a connection | `hydromodpy/spatial/mesh/ops/mesh_orthogonality.py` (`connection_nonorthogonality_deg`, `nonorthogonality_summary`) |
| The XT3D decision | `hydromodpy/solver/modflow6/builders/solver_options.py` (`resolve_xt3d_decision`) |
| The Gmsh sizes | `hydromodpy/spatial/mesh/gmsh_grid/zone_meshing/_gmsh_fields.py`, `_gmsh_occ.py` (`apply_mesh_options`), `_build_context.py` (`compute_effective_max_size`), `config.py` (`ZoneMeshingSettings`) |
| The mesh phase and its cache | `hydromodpy/workflow/steps/mesh.py` (`run_mesh_phase`), `hydromodpy/spatial/mesh/mesh_cache.py` |
| The DISV export | `hydromodpy/spatial/mesh/adapters/flopy_adapter.py` (`to_flopy_disv_args`), `hydromodpy/solver/modflow6/build.py` |
| The QA summary of a mesh | `hydromodpy/spatial/mesh/gmsh_grid/zone_meshing/_summary_sidecar.py`, `orchestration/reporting.py` |

## See also

- {doc}`solvers`: what the solvers do with the cells.
- {doc}`solvers/xt3d-on-irregular-disv-meshes`: the XT3D terms and their trigger.
- {doc}`groundwater-flow`: the equation the cells discretise.
- {doc}`../reference/parameters/mesh_catchment`: the mesher section as a reference page.

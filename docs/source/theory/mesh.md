# The mesh

The solver does not see the DEM. It sees cells, and one top elevation, one bottom
elevation and one centre for each of them. This page gives the rules that turn the
DEM into those cells: which engine lays the cells out, how the top of a cell is read from
the DEM, how many cells a given size costs, and which checks the code runs on the
result.

:::{note}
**Scope.** The cell layout below is the one of MODFLOW 6, which reads every grid as a
DISV grid. MODFLOW-NWT and Boussinesq read one engine each, and a file that pairs a solver with
an engine it does not read is refused when it is read; the pairs are on
{doc}`../contribute/architecture/mesh/mesh-engines`. Boussinesq ignores the top sampling of {ref}`mesh-top`. What the
solver does with the cells is on {doc}`solvers`. The extra terms XT3D adds on a non-orthogonal mesh are on
{doc}`solvers/xt3d-on-irregular-disv-meshes`. To set up a mesh, see
{doc}`../reference/parameters/mesh`.
:::

## The chain in one list

The code builds the cells in this order. Each step is a section below.

1. Two surfaces: the top from the DEM $Z$ and the bottom from the depth model.
2. A planar mesh from one of three engines, chosen by {toml}`mesh.engine`: squares on the
   DEM ({ref}`mesh-structured`), triangles ({ref}`mesh-triangle`) or Voronoi cells
   ({ref}`mesh-voronoi`). The two engines that grade their cells follow one size field
   ({ref}`mesh-size`).
3. One top elevation per cell ({ref}`mesh-top`) and one bottom elevation per cell.
4. A check of the thickness ({ref}`mesh-acceptance`), then the layers
   ({ref}`mesh-layers`).
5. The export to MODFLOW 6 as a DISV grid. The cells that have no valid top or bottom
   are written inactive.

What each engine gives the solver:

| Engine | Cells | Centre | Connections | Lines it follows |
|---|---|---|---|---|
| `regular` | squares, one per DEM pixel or larger | cell centre | orthogonal | rivers as chains of cells; contacts and shores as staircases |
| `triangle` | triangles | mean of the vertices | not orthogonal, XT3D on by default | rivers, contacts and shores as edges |
| `voronoi` | polygons | the generator | orthogonal | rivers as chains of cells; contacts and shores as faces |

Example 04 uses the first engine: its files declare no `[mesh]` section, so every cell is one
DEM pixel. The header of `step1_minimal.toml` counts 21406 cells of 75 m for this domain.

::::{dropdown} Notation of this page
```{hmp-notation}
```
::::

(mesh-structured)=
## 1. The regular engine

With no `[mesh]` section, or with `engine = "regular"` and no {toml}`mesh.cell_size`, the
cells are the pixels of the top raster, with the same size and the same extent. A cell
$(i,j)$ takes the value of pixel $(i,j)$, with no interpolation:

$$
z_{\mathrm{top},ij} = Z_{ij}, \qquad N_S = n_{\mathrm{row}}\, n_{\mathrm{col}}, \qquad
a_{ij} = \Delta_x \Delta_y .
$$

A pixel that is nodata makes the cell inactive. The cell still exists in the grid, so
$N_S$ counts the active and the inactive cells.

With a {toml}`mesh.cell_size` coarser than the pixel, the grid covers the same extent with
$\operatorname{round}(L_x / \ell_g)$ cells along an extent $L_x$, so the cells are a little
larger or smaller than asked. Top and bottom are resampled to that shape with a bilinear
rule. If a cell then covers at least two DEM pixels, the top of the cell is the zonal
statistic of {ref}`mesh-top` instead of the resampled value. A grid whose cells are the
pixels is never touched by the zonal top. A {toml}`mesh.cell_size` finer than the DEM is
refused. The developer key {toml}`mesh.regular.shape` gives the number of rows and columns
instead of a size.

The engine does not grade its cells: it ignores {toml}`mesh.river_cell_size` and
{toml}`mesh.river_band`, and its quality report says so. A river is the chain of cells its
line crosses. A contact or a lake shore becomes a staircase of cell faces, and the report
gives the distance between the staircase and the line. A flow barrier is the staircase of the
faces whose two cell centres its line separates.

MODFLOW 6 reads this grid as a DISV grid. MODFLOW-NWT reads it as a DIS grid.

(mesh-size)=
## 2. The size field of the graded engines

The `triangle` and `voronoi` engines mesh under one size field $\ell(\mathbf{x})$, the
wanted cell size at each point, computed on the grid of the DEM. The background size is
$\ell_g$, {toml}`mesh.cell_size`, which is the DEM pixel when unset. A line the mesh refines
is a term of the field: the cells have the size $\ell_s$ on it, and the size grows back to
$\ell_g$ with the distance $\xi$ to the line. The rivers are such a line, with $\ell_s$ set
by {toml}`mesh.river_cell_size` and the distance $\xi_s$ over which the size grows back
set by {toml}`mesh.river_band`. The shore of a lake and the zones of
{toml}`mesh.refinement_zone.cell_size` are others. A term grows at
$\sigma_k = \min\bigl((\ell_g - \ell_{s,k}) / \xi_{s,k},\ \sigma_{\max}\bigr)$ per metre,
and the field is the minimum of the background and of every term:

$$
\ell(\mathbf{x}) = \min\Bigl(\ell_b(\mathbf{x}),\ \min_k\bigl[\ell_{s,k}
+ \sigma_k\, \xi_k(\mathbf{x})\bigr]\Bigr).
$$ (eq-mesh-size)

The distances $\xi_k$ are Euclidean distances between pixel centres. The field is kept above
the DEM pixel $\Delta$, since a cell finer than the DEM adds no information. The background
$\ell_b$ is $\ell_g$ inside the catchment and grows to $\kappa\,\ell_g$ outside it, with
$\kappa$ = {toml}`mesh.outside_factor`, over at least {toml}`mesh.transition_distance`, so the cells
far from the catchment are coarse.

Every term grows at most at $\sigma_{\max}$ = {toml}`mesh.max_slope` per metre, and so does their
minimum. Two neighbouring cells, about one cell apart, then differ in size by a ratio of at most
about $(1 + \sigma_{\max}/2)/(1 - \sigma_{\max}/2)$, which is 1.67 for the default 0.5. A smaller
slope gives a smoother mesh and more cells. The `regular` engine ignores the field, and so does
a triangulation read from a file.

(mesh-triangle)=
## 3. The triangle engine

The `triangle` engine builds a constrained Delaunay triangulation of $\Omega$ with Gmsh
{cite:p}`geuzaine2009gmsh` under the size field of {ref}`mesh-size`. The river lines, the
geology contacts, the lake shores and the flow barriers are embedded as edges of the
triangulation, so a contact, a shore or a barrier is a chain of edges and no triangle holds
two zones. The cells of a river
are the triangles on one bank of its line.

The centre of a triangle is the mean of its three vertices. The line between two centres is
then not perpendicular to the edge the triangles share: the connection has an angle
({ref}`mesh-angle`), and MODFLOW 6 turns XT3D on by default for a triangle mesh (an explicit
{toml}`modflow6.runtime.mf6_enable_xt3d` wins).

Gmsh does not give the same triangulation twice for the same input. The engine keeps the first
one in the project (`.hmp/mesh_cache/`) and reuses it while the request, the engine version and
the builds of Gmsh and of the geometry libraries are the same. A triangulation that already
exists is read with {toml}`mesh.triangle.path` instead of generated.

(mesh-voronoi)=
## 4. The Voronoi engine

The cells of the `voronoi` engine are the Voronoi (PEBI) cells of generators
$\mathbf{s}_i$: the set of points closer to $\mathbf{s}_i$ than to any other generator,
clipped to the outline $\Omega$ of the domain. The generator is the cell centre written to the
DISV file. The engine places the generators itself:

- one generator on each vertex of a river line, so that the river runs through the centres of
  a chain of cells;
- a pair of mirror generators across each segment of a geology contact, of a lake shore, of a
  flow barrier or of the catchment boundary, after {cite:t}`berge2019voronoi`, so that the
  segment is the perpendicular bisector of the pair and a face of the mesh;
- generators on the boundary of the domain;
- free generators for the rest, drawn with the density $\ell^{-2}$ and moved by a Lloyd
  relaxation weighted by $\ell^{-4}$ until the cells have the size of the field.

The construction, its gates and its limits are on
{doc}`../contribute/architecture/mesh/voronoi-engine`. Three consequences follow.

**The number of cells.** The engine draws about $\int_\Omega \ell^{-2}\,\mathrm{d}A$
generators, one per cell of area $\ell^2$. With a uniform size it gives $N_V = A_\Omega /
\ell_g^2$ cells: as many as a grid of pixels of side $\ell_g$ ({ref}`mesh-budget`).

**The faces.** The face between two cells is the perpendicular bisector of the segment between
their generators. A river is not a face: it runs through the middle of a chain of cells. A
contact or a shore is a face, so the conductivity of a cell is the one of its zone, and the
cells of a lake are the cells inside its shore. Where a river crosses a contact the river
wins: the contact yields on a short segment, the pair joins the river chain a little off the
line, and the top of such a cell is the minimum of its pixels ({ref}`mesh-top`). A flow barrier
never yields: the river chain crosses it through a barrier face between two of its cells.

**The orthogonality.** The line between the two centres is perpendicular to the face, so
$\varphi_{nm} = 0$ on every connection whose two cells kept their generator as centre.
{ref}`mesh-angle` says why this matters. As a check, 36 generators on a $6 \times 6$ lattice
(the 16 inner ones moved at random) have 50 Delaunay triangles, and `voronoi_planar_mesh`
returns 36 cells with $0^\circ$ on every connection.

(mesh-angle)=
## 5. Flow between two cells, and the angle

MODFLOW 6 writes the flow between two cells with the two-point finite-difference term
$G_{nm}\,(h_m - h_n)$ of {eq}`eq-cell-balance` {cite:p}`harbaugh2005,langevin2017`. It is
exact only when the conductivity is isotropic in the plane and the line between the
centres is perpendicular to the shared face. HydroModPy measures the departure from
that condition on every connection, as an angle. With $\mathbf{d}_{nm}$ the vector
between the two centres and $\mathbf{n}_{nm}$ the unit normal of the shared edge:

$$
\varphi_{nm} = \arccos\!\left(\frac{\lvert \mathbf{d}_{nm} \cdot \mathbf{n}_{nm} \rvert}
{\lVert \mathbf{d}_{nm} \rVert}\right).
$$ (eq-nonorthogonality)

Only an edge shared by exactly two cells counts as a connection. The summary the code
keeps is the median, the 95th and 99th percentiles, the maximum and the share of
connections above 30 degrees. What the angle does to the flux, and when the code turns
on the XT3D option that corrects it, is on {doc}`solvers/xt3d-on-irregular-disv-meshes`.

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

```{eval-rst}
.. plot:: theory/figures/mesh_voronoi.py
   :alt: Two triangles with their connection vector and face normal, and a triangulation of 36 seeds with its Voronoi dual.
   :caption: Left: the two triangles above, with :math:`\mathbf{d}_{nm}` between the
      centres and :math:`\mathbf{n}_{nm}` normal to the shared face; the angle comes from
      ``connection_nonorthogonality_deg``. Right: the 36 seeds of the check of
      :ref:`mesh-voronoi`, their 50 triangles (dotted) and the 36 cells of
      ``voronoi_planar_mesh`` (blue). Look at the title: the triangles reach 35°, every
      connection of the dual is at 0°.
```

(mesh-top)=
## 6. The top of a cell

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
cell often falls on a bank, not on the thalweg, and the cell is then too high. On a `voronoi` mesh, a cell of
a river chain whose centre lies off the river line (where a contact crosses the river,
where two thalwegs share a cell, at the end of a river near the boundary) takes the
minimum of the pixels it covers, also in this mode.

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
order. The first one guards against a nodata edge:

$$
\text{if } \lvert z_{\mathrm{top},c} - \tilde z_c \rvert > \varepsilon_z
\text{ on a hillslope cell:}\quad z_{\mathrm{top},c} \leftarrow \tilde z_c.
$$

Channel cells are exempt, since they are lowered on purpose. It is off when
$\varepsilon_z = 0$. The second one keeps a lowered top above the bottom. On the regular grid
the top is raised:

$$
z_{\mathrm{top},c} \leftarrow \max\bigl(z_{\mathrm{top},c},\ z_{\mathrm{bot},c} + b_{\min}\bigr)
\quad \text{on every active cell.}
$$

On a triangle or Voronoi mesh the top stays where the pixels put it, and the bottom follows
it down when the lowered top leaves less than $b_{\min}$, or less than a tenth of the column
of the centre sample:

$$
z_{\mathrm{bot},c} \leftarrow z_{\mathrm{top},c}
- \max\bigl(\tilde z_c - z_{\mathrm{bot},c},\ b_{\min}\bigr).
$$

A coarse cell on the flank of a pit then keeps the thickness of its centre sample, where a
raised top would leave a column of a few decimetres next to neighbours of tens of metres,
which MODFLOW 6 cannot solve under Newton. A cell whose column stays thick enough is
unchanged, and the bottom of every other cell keeps its centroid value, so a lowered top
thins every layer of that column. The code logs, once per build, how many cells took a zonal
value, how many are channel cells, how far the tops were lowered, and how many bottoms
followed.

```{eval-rst}
.. plot:: theory/figures/mesh_zonal_top.py
   :alt: A hexagonal cell over a DEM with an incised channel, and the elevations of its pixels with three candidate tops.
   :caption: A cell of 32 m radius over a DEM of 5 m pixels, its centre on a bank 18 m from
      a channel incised 2 m (blue). Right: the elevation of each pixel inside the cell,
      and the top three rules give, from ``zonal_top`` with ``channel_stat = "min"`` and
      ``hillslope_stat = "median"``. Look at the gap: the centroid sample and the
      hillslope median sit on the bank, about 4 m above the channel minimum the cell
      takes when the stream raster is read.
```

The zonal rule falls back to the centroid value, with a message in the log, in three
cases: a surface with no georeferencing (`Zonal top sampling needs a georeferenced surface; using centroid sample.`),
a channel source with no stream raster (`Zonal channel_source=%s but no stream raster found`;
the channel class is then off), and a structured grid whose cells cover fewer than two DEM
pixels (`Zonal top sampling skipped: a grid cell`). In the code: `zonal_top`.

(mesh-layers)=
## 7. Thickness and layers

The column of each cell is cut into layers by shares of its thickness, the same shares in
every cell, set by {toml}`modflow6.sgrid.vertical.genmtd_lay`. The rule,
{eq}`eq-layer-bottom`, and its three strategies are on {ref}`gwf-layers`.

Every layer shares the cells of the plan: the mesh is a vertical extrusion. A cell is inactive in every layer when its top or its bottom is nodata,
not finite, or at or below the nodata value.

(mesh-budget)=
## 8. How many cells a size costs

The cost of a run grows with the number of cells, so a structured grid and a mesh are
compared at equal cell count. The ideal count below assumes cells of one uniform size over
an area $A_\Omega$. With a size field, $A_\Omega/\ell^2$ becomes
$\int_\Omega \ell(\mathbf{x})^{-2}\,\mathrm{d}A$.

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

In the table, $\ell$ is the distance between two generators for the Voronoi cells and the side
of a triangle. The two engines do not read {toml}`mesh.cell_size` the same way. For the
`voronoi` engine it is the square root of the area of a cell: a size equal to the pixel gives
the cell count of the grid, with generators $1.07$ sizes apart. For the `triangle` engine it
is the side of a triangle, which Gmsh takes as its target: a size equal to the pixel gives about $2.3$
times the cell count of the grid for equilateral triangles, and Gmsh makes about $2.6$ to $2.7$ times
on a uniform field.

**Worked example.** The 21406 cells of 75 m of the header of `step1_minimal.toml` (the file does not say if
the count includes the inactive cells) cover
$21406 \times 75^2\ \mathrm{m^2} \approx 120\ \mathrm{km^2}$. The same count on a
Voronoi mesh means generators about $81\ \mathrm{m}$ apart, a {toml}`mesh.cell_size` of
$75\ \mathrm{m}$; on a triangle mesh, triangles of about $114\ \mathrm{m}$ side. These are ideal figures: a real mesh refines near the
interfaces, and the count of a run is the number of cells ($\mathrm{ncpl}$) of its DISV
file.

```{eval-rst}
.. plot:: theory/figures/mesh_cell_count.py
   :alt: Number of cells against cell size for square pixels, Voronoi cells and triangles, on log axes.
   :caption: :eq:`eq-cell-count` for :math:`A_\Omega` = 120 km². The three lines are
      parallel: halving the size multiplies the count by four for every layout. Look at
      the dots, 21406 cells each: 75 m pixels, Voronoi generators 81 m apart, triangles of
      114 m.
```

$N_S$ counts the cells of the whole raster box, active or not ({ref}`mesh-structured`);
every cell of a mesh lies in $\Omega$.

(mesh-acceptance)=
## 9. The checks the code applies

The mesh is refused when its inputs are wrong, and a run stops when the grid it solves is not
the mesh that was stored. The code does not compute a minimum angle, an aspect ratio or a
skewness, and it refuses no mesh for its shape, with the exception of the build of the `voronoi`
engine. The table lists what it does check. Where a limit is a number, the table names the
constant that holds it.

| What is checked | Rule | What happens | Where |
|---|---|---|---|
| Solver and mesh | the solver reads the engine of `[mesh]` | refused when the file is read: `reads the meshes of the engines` | `accepted_meshes` of the flow adapters, checked by `HydroModPyConfig` |
| Size of the regular grid | not finer than the DEM pixel | refused when the mesh is built: `the regular engine cannot mesh finer than the DEM` | `plan_layout` in `engines/regular/grid.py` |
| Size of the rivers | {toml}`mesh.river_cell_size` at most {toml}`mesh.cell_size` | refused when the file is read | `MeshConfig` in `spatial/mesh/config/mesh.py` |
| Voronoi build | every cell covers its generator, the conformal faces lie on their lines, each river chain is connected, the areas add up to the domain, no repeated vertex, no face under a micrometre | the build stops with `MeshGenerationError`, never a warning | `engines/voronoi/gates.py` |
| Solved grid | the DISV or DIS grid of the solver is the stored mesh | the run stops with `IncompatibleMeshError` | the extractors of the solvers |
| Top and bottom overlap | at least one cell where both are valid | refused: `No finite overlapping valid cells found between top and bottom surfaces.` | `assert_bottom_below_top` in `sgrid_generation.py` |
| Bottom below top | strictly, on every valid cell | refused: `Bottom surface must be strictly below top surface on valid cells` | the same function |
| Cells much thicker than the rest | thickness above the larger of 10 times the median and 500 m | warning only, triangle and Voronoi meshes only: `Aquifer thickness outliers:` | `_warn_on_outlier_thickness`; constants `_THICKNESS_OUTLIER_FACTOR` and `_THICKNESS_OUTLIER_FLOOR_M` in `discretization_spatial.py` |
| Non-orthogonality | the trigger of {doc}`solvers/xt3d-on-irregular-disv-meshes` | XT3D switched on, not a refusal | `resolve_xt3d_decision` |
| Zonal top | $n_{\min}$, $\varepsilon_z$, $b_{\min}$ and a tenth of the column | fallback, clamp or bottom moved, counted in the log | `zonal_top` in `zonal_stats.py`, `_bottom_under_lowered_top` in `discretization_spatial.py`; the keys are on the cards below |
| Structured grid for the zonal top | each cell covers at least two DEM pixels | zonal top skipped, resampled top kept | `_cells_cover_pixels` (argument `min_pixels`) |

The quality report of a mesh, `MeshQA`, is stored with it (the attribute `qa` of `mesh/`). It
holds the areas, the size ratio between neighbours, the offset of a centre from the centroid of
its cell, the non-orthogonality and, for each line family, how much of the line the faces
follow. Four fields give the same per cell, computed on read: `mesh_cell_area`,
`mesh_neighbour_ratio`, `mesh_center_offset` and `mesh_nonorthogonality`. The report is not a
verdict: a mesh with a poor report still runs.

## Assumptions

- A cell has one top and one bottom. The surface inside the cell is flat.
- A mesh is fixed for the run. It does not move with the water table.
- The conductivity is isotropic in the plane. The code writes no input for horizontal
  anisotropy.
- The coordinates are in a projected CRS in metres. The size field, the 1 mm merge of the
  vertices of the Voronoi tessellation and every distance of the engines read this.
- The zonal rule treats a channel pixel as a pixel of the stream raster of the
  delineation. It does not read the observed network.

(mesh-limits)=
## Limits

- **The regular grid does not refine.** Its cells have one size, a line becomes a staircase of
  faces, and a side head applies half a cell inside the side. Use the `triangle` or the
  `voronoi` engine for a mesh finer along the rivers.
- **Some solvers read one engine.** Boussinesq cannot run on Voronoi cells, nor MODFLOW-NWT on a
  refined mesh. The zonal top of MODFLOW-NWT needs
  {toml}`modflownwt.sgrid.top_sampling.channel_source` at `"none"`: the file is refused
  otherwise.
- **Gmsh is not reproducible.** Two builds of the same input give meshes with different cell
  counts. The cache of `.hmp/mesh_cache/` pins the first one; deleting it changes the mesh of
  a resumed run, and `restart_from` refuses a run solved on another mesh.
- **The Voronoi mesh is reproducible on one platform.** One request and one seed give one mesh
  on one machine, GEOS and scipy build. Another build can give a mesh with the same quality
  and another connectivity.
- **The size ratio has a floor.** Where the field grows at its largest slope, two neighbouring
  Voronoi cells differ by about $(1 + \sigma_{\max}/2)/(1 - \sigma_{\max}/2)$, and the centre of a
  cell sits off its centroid by about a quarter of the slope times the cell size. The report
  states both.
- **Narrow lake arms are not followed.** A closed line whose arms are narrower than the local
  cell cannot hold a pair of generators in each arm: the faces follow part of the shore, and
  the cells of the lake are those the lake polygon overlaps.
- **Side heads sit at different distances from the side.** A head imposed on a side applies to
  the cells that have a face on it, at the distance of their centres: half a cell on a regular
  grid, a third of the height on triangles, none on Voronoi cells. The report states it.
- **A thin column is lengthened, not refused.** The tenth of the column that moves a bottom
  with a lowered top is an empirical threshold, chosen so that the cells next to a quarry
  stay solvable. It derives from nothing else.
- **No shape check.** A sliver, an abrupt change of size or a high non-orthogonality does
  not stop a run, except in the build of the `voronoi` engine. The non-orthogonality is the only
  shape measure the code reads, and it decides about XT3D, not about the mesh.
  `connection_nonorthogonality_deg` and `nonorthogonality_summary` can be called on any
  planar `HydroMesh` for a closer look.
- **Not a 3D mesh.** The layers are an extrusion of the plan. A footprint that changes
  from one layer to the next, or a refinement in depth, is not represented.
- **An outlier thickness only warns.** A nodata value read as an elevation gives a cell
  that is kilometres deep, with a clean top, and the run converges. The warning of
  {ref}`mesh-acceptance` is the only sign, and a structured grid does not emit it.

The keys of the layers and of the top are in {doc}`[modflow6] <../reference/parameters/modflow6>`
and those of the mesh in {doc}`[mesh] <../reference/parameters/mesh>`.

## Parameters of this page

The keys that choose the engine, the size and the top. The cards show the defaults and the
allowed values. The developer keys are behind the developer button.

```{hmp-params}
mesh.engine
mesh.cell_size
mesh.river_cell_size
mesh.river_band
mesh.max_slope
mesh.outside_factor
mesh.transition_distance
mesh.seed
mesh.regular.shape
mesh.families.rivers
mesh.families.geology
mesh.families.lakes
mesh.families.barriers
mesh.families.watershed_boundary
mesh.triangle.path
mesh.triangle.algorithm
mesh.voronoi.seeds
mesh.voronoi.lloyd_tolerance
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
hydromodpy.spatial.mesh.engines
hydromodpy.spatial.mesh.sizing
hydromodpy.spatial.mesh.ops.voronoi
hydromodpy.spatial.mesh.ops.zonal_stats
hydromodpy.spatial.mesh.ops.mesh_orthogonality
hydromodpy.spatial.mesh.cartesian_grid.sgrid_generation
hydromodpy.solver.modflow_grid.discretization_spatial
hydromodpy.solver.modflow6.builders.solver_options
```

## In the code

| What | Where |
|---|---|
| The surfaces, the plan, the top, the layers | `hydromodpy/solver/modflow_grid/discretization_spatial.py` (`build_spatial_discretization`, `resolve_domain_surfaces`), `hydromodpy/spatial/mesh/cartesian_grid/sgrid_generation.py` (`layer_proportions`) |
| The keys of the layers and of the top | `hydromodpy/spatial/mesh/cartesian_grid/sgrid_config.py` |
| The keys of the mesh | `hydromodpy/spatial/mesh/config/mesh.py` (`MeshConfig`) |
| The engines and their registry | `hydromodpy/spatial/mesh/engines/` (`regular`, `triangle`, `voronoi`), `hydromodpy/spatial/mesh/registry.py` |
| The request and the planner | `hydromodpy/spatial/mesh/request.py`, `hydromodpy/spatial/mesh/planning/plan.py` (`plan_mesh_request`) |
| The size field | `hydromodpy/spatial/mesh/sizing/size_field.py` (`build_size_field`) |
| The centroid sample | `hydromodpy/spatial/surface_sampling.py` (`PreparedSurfaceSampler.sample`) |
| The zonal top | `hydromodpy/spatial/mesh/ops/zonal_stats.py` (`zonal_top`), `discretization_spatial.py` (`_zonal_top_flat`, `_zonal_structured_top`, `_bottom_under_lowered_top`) |
| The channel mask | `hydromodpy/solver/modflow6/build.py` (`_resolve_channel_mask_for_zonal`) |
| The Voronoi tessellation | `hydromodpy/spatial/mesh/engines/voronoi/tessellation.py`, `hydromodpy/spatial/mesh/ops/voronoi.py` (`voronoi_planar_mesh`) |
| The angle of a connection | `hydromodpy/spatial/mesh/ops/mesh_orthogonality.py` (`connection_nonorthogonality_deg`, `nonorthogonality_summary`) |
| The XT3D decision | `hydromodpy/solver/modflow6/builders/solver_options.py` (`resolve_xt3d_decision`) |
| The mesh step and its cache | `hydromodpy/workflow/steps/mesh.py` (`step_mesh`), `hydromodpy/spatial/mesh/cache.py` |
| The DISV export | `hydromodpy/spatial/mesh/adapters/flopy_adapter.py` (`to_flopy_disv_args`), `hydromodpy/solver/modflow6/build.py` |
| The quality report of a mesh | `hydromodpy/spatial/mesh/model/mesh_qa.py` (`compute_mesh_qa`) |

## See also

- {doc}`solvers`: what the solvers do with the cells.
- {doc}`solvers/xt3d-on-irregular-disv-meshes`: the XT3D terms and their trigger.
- {doc}`groundwater-flow`: the equation the cells discretise.
- {doc}`../reference/parameters/mesh`: the mesh section as a reference page.
- {doc}`../contribute/architecture/mesh/mesh-engines`: the port, the planner and the three engines.

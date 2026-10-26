# The mesh

The solver does not see the DEM. It sees cells, each with one top, one bottom and one centre.
This page explains how the code builds these cells from the DEM and how it checks them.

:::{note}
MODFLOW 6 reads every grid as a DISV grid, and this page follows it. MODFLOW-NWT and
Boussinesq read one engine each ({doc}`../contribute/architecture/mesh/mesh-engines`), and
Boussinesq ignores the top sampling of {ref}`mesh-top`. The use of the cells by the solvers is
on {doc}`solvers`, the XT3D terms on {doc}`solvers/xt3d-on-irregular-disv-meshes` and the keys
on {doc}`../reference/parameters/mesh`.
:::

## The chain in one list

The code builds the cells in this order.

1. The top from the DEM $Z$, the bottom from the depth model.
2. A planar mesh from the engine of {toml}`mesh.engine`: squares ({ref}`mesh-structured`),
   triangles ({ref}`mesh-triangle`) or Voronoi cells ({ref}`mesh-voronoi`). The planner first
   cleans the lines the mesh follows ({ref}`mesh-cleanup`), and the last two engines follow a
   size field ({ref}`mesh-size`).
3. One top ({ref}`mesh-top`) and one bottom per cell.
4. A check of the thickness ({ref}`mesh-acceptance`), then the layers ({ref}`mesh-layers`).
5. The export to MODFLOW 6 as a DISV grid. A cell with no valid top or bottom is inactive.

| Engine | Cells | Centre | Connections | Lines it follows |
|---|---|---|---|---|
| `regular` | squares, one per DEM pixel or larger | cell centre | orthogonal | rivers as chains of cells, contacts and shores as staircases |
| `triangle` | triangles | mean of the vertices | not orthogonal, XT3D on by default | rivers, contacts and shores as edges |
| `voronoi` | polygons | the generator | orthogonal | rivers as chains of cells, contacts and shores as faces |

::::{dropdown} Notation of this page
```{hmp-notation}
```
::::

(mesh-structured)=
## 1. The regular engine

With no `[mesh]` section, or with `engine = "regular"` and no {toml}`mesh.cell_size`, the
cells are the pixels of the top raster and take their values with no interpolation:

$$
z_{\mathrm{top},ij} = Z_{ij}, \qquad N_S = n_{\mathrm{row}}\, n_{\mathrm{col}}, \qquad
a_{ij} = \Delta_x \Delta_y .
$$

A nodata pixel makes its cell inactive, and $N_S$ counts that cell too. A coarser
{toml}`mesh.cell_size` gives $\operatorname{round}(L_x/\ell_g)$ cells along an extent $L_x$.
The code resamples the top and the bottom with a bilinear rule. In the zonal mode of
{ref}`mesh-top`, a cell that covers two DEM pixels or more takes the zonal top instead. The
engine refuses a finer size with `the regular engine cannot mesh finer than the DEM`. The
developer key {toml}`mesh.regular.shape` gives the rows and columns instead.

The engine ignores {toml}`mesh.river_cell_size` and {toml}`mesh.river_band`, so a mesh finer
along the rivers needs the `triangle` or the `voronoi` engine. A river is the chain of cells
its line crosses. A contact or a shore becomes a staircase of faces, whose
distance to the line is in the quality report. A barrier takes the faces whose two centres its
line separates. MODFLOW-NWT reads this grid as a DIS grid.

(mesh-size)=
## 2. The lines and the size field

(mesh-cleanup)=
### Cleaning the lines

Rivers, lake shores and geology contacts come from different sources, so they often miss each
other by a few metres or carry tiny holes and repeated vertices. Before it computes any size,
the planner cleans the domain and the families of {toml}`mesh.families`, at a tolerance of a
tenth of a DEM pixel. It leaves a triangulation read from a file as it is. It drops the holes
smaller than the square of the local cell size, and an island counts as a hole of its lake. It
merges close vertices but keeps those another line holds, so a barrier laid on a shore stays on
it. It cuts back a river
or contact end that runs along another line, and it snaps a line end onto a line it almost
touches. A barrier is never cut back, because its length is physical. The log and the mesh QA
count each change.

### The size field

The `triangle` and `voronoi` engines mesh under one size field $\ell(\mathbf{x})$, the wanted
cell size on the DEM grid. The background size $\ell_g$ is {toml}`mesh.cell_size`, or the DEM
pixel when unset. Each refined line or zone adds a term. For the rivers, the size is
$\ell_s$ = {toml}`mesh.river_cell_size` on the line and grows back to $\ell_g$ over the
distance $\xi_s$ = {toml}`mesh.river_band`. Lake shores and the zones of
{toml}`mesh.refinement_zone.cell_size` are other terms. The field reads

$$
\ell(\mathbf{x}) = \min\Bigl(\ell_b(\mathbf{x}),\ \min_k\bigl[\ell_{s,k}
+ \sigma_k\, \xi_k(\mathbf{x})\bigr]\Bigr),
$$ (eq-mesh-size)

where $\xi_k$ is the distance to line $k$ and
$\sigma_k = \min\bigl((\ell_g - \ell_{s,k}) / \xi_{s,k},\ \sigma_{\max}\bigr)$ its growth per
metre. The field never goes below the DEM pixel $\Delta$. The background $\ell_b$ is $\ell_g$
in the catchment and grows outside to $\kappa\,\ell_g$, with $\kappa$ =
{toml}`mesh.outside_factor`, over at least {toml}`mesh.transition_distance`. Since
$\sigma_{\max}$ = {toml}`mesh.max_slope` bounds every term, two neighbouring cells differ in
size by a ratio of at most about $(1 + \sigma_{\max}/2)/(1 - \sigma_{\max}/2)$, which is 1.67
for the default 0.5. A smaller slope gives a smoother mesh and more cells. A triangulation read
from a file ignores the field.

```{eval-rst}
.. plot:: theory/figures/mesh_size_field.py
   :alt: The cell size around a river, in plan and against the distance to the river.
   :caption: Left: the field around a river (white) in a catchment (dashed). Right: the size
      against the distance to the river. A band of 20 m asks for a slope of 2, and
      ``build_size_field`` holds it at 0.5.
```

(mesh-gap)=
### The gap between face lines

A cell larger than the space between two lines it has to follow cannot follow both. So the
face lines (lake shores, barriers, contacts, the catchment boundary) and the domain outline add
a term. At each point of a line, the gap $e$ is the distance to the nearest point of another
line. The same line counts as another when the way along it is more than twice the straight
distance. So a narrow lake arm makes a gap, and so does a corner sharper than 53 degrees, but a
right-angle junction makes none. The planner sizes the chord of a gap inside the domain as

$$
\ell_e = \max\bigl(e / n_e,\ \Delta\bigr),
$$ (eq-gap-size)

where $n_e$ = {toml}`mesh.gap_cells` is the number of cells across, 2 by default and 0 to
switch the term off. After rounding, a gap holds $n_e$ to $1.19\,n_e$ cells. The rivers stay
out, because a river is a chain of cells. On a generated Voronoi mesh with lakes, only the
shores the faces follow count.

(mesh-triangle)=
## 3. The triangle engine

The `triangle` engine builds a constrained Delaunay triangulation of $\Omega$ with Gmsh
{cite:p}`geuzaine2009gmsh` under the size field. Rivers, contacts, shores and barriers are
edges, so no triangle holds two zones, and the cells of a river are the triangles on one bank.
The centre of a triangle is the mean of its vertices, so a connection has an angle
({ref}`mesh-angle`), and MODFLOW 6 turns XT3D on by default. An explicit
{toml}`modflow6.runtime.mf6_enable_xt3d` wins. Gmsh does not give the same triangulation twice
for one input, so the engine keeps the first one in `.hmp/mesh_cache/`. It reuses it while the
request, the engine version and the builds of Gmsh and of the geometry libraries stay the same.
{toml}`mesh.triangle.path` reads an existing triangulation instead.

(mesh-voronoi)=
## 4. The Voronoi engine

A cell of the `voronoi` engine is the Voronoi (PEBI) cell of a generator $\mathbf{s}_i$, the
points closer to $\mathbf{s}_i$ than to any other generator, clipped to the outline $\Omega$.
The generator is the cell centre. The engine puts one generator on each vertex of a river
line, so the river runs through a chain of centres. It puts a pair of mirror generators across
each segment of a contact, a shore, a barrier or the catchment boundary, after
{cite:t}`berge2019voronoi`, so the segment is a face. Other generators sit on the domain
boundary. Free generators fill the rest with the density $\ell^{-2}$, and a Lloyd relaxation
weighted by $\ell^{-4}$ moves them. So the engine draws about $\int_\Omega \ell^{-2}\,\mathrm{d}A$
generators, one per cell of area $\ell^2$ ({ref}`mesh-budget`).

So each cell lies in one zone, and the cells of a lake are those inside its shore. Where a
river crosses a contact, the contact yields on a short segment, and the river cell there takes
the minimum of its pixels as top ({ref}`mesh-top`). A flow barrier never yields, and the river
chain crosses it through a barrier face. Every face is the perpendicular bisector of two
generators, so $\varphi_{nm} = 0$ where both cells kept their generator as centre. As a check,
36 generators on a $6 \times 6$ lattice, the 16 inner ones moved at random, give 36 cells at
$0^\circ$ on every connection. The construction and its gates are on
{doc}`../contribute/architecture/mesh/voronoi-engine`.

(mesh-angle)=
## 5. Flow between two cells, and the angle

MODFLOW 6 writes the flow between two cells as $G_{nm}\,(h_m - h_n)$, the two-point term of
{eq}`eq-cell-balance` {cite:p}`harbaugh2005,langevin2017`. It is exact only when the
conductivity is isotropic in the plane and the line between the centres is perpendicular to
the shared face. The code measures the departure as an angle. With $\mathbf{d}_{nm}$ the vector
between the centres and $\mathbf{n}_{nm}$ the unit normal of the shared edge, it reads

$$
\varphi_{nm} = \arccos\!\left(\frac{\lvert \mathbf{d}_{nm} \cdot \mathbf{n}_{nm} \rvert}
{\lVert \mathbf{d}_{nm} \rVert}\right).
$$ (eq-nonorthogonality)

Over the edges shared by two cells, the code keeps the median, the 95th and 99th percentiles,
the maximum and the share of angles above 30 degrees. The effect on the flux and the XT3D
trigger are on {doc}`solvers/xt3d-on-irregular-disv-meshes`. For example, the two triangles of
a $2 \times 1$ rectangle cut along its diagonal have their centres at $(2/3, 1/3)$ and
$(4/3, 2/3)$, so $\cos\varphi = 4/5$ and $\varphi \approx 36.9^\circ$. The four corners of the
same rectangle, taken as seeds, give four Voronoi cells of $1 \times 0.5$, all at $0^\circ$.

```{eval-rst}
.. plot:: theory/figures/mesh_voronoi.py
   :alt: Two triangles and their angle, and 36 seeds with their Voronoi cells.
   :caption: Left: the two triangles above. Right: the 36 seeds of the check of
      :ref:`mesh-voronoi`, their 50 triangles (dotted) and their Voronoi cells (blue).
```

The two-point term also assumes that the line of the centres crosses the face in its middle.
On a face of length $L$ crossed at a distance $s$ from one end, the bisection offset is

$$
\beta = \frac{\lvert s - L/2 \rvert}{L},
$$ (eq-bisection-offset)

which is 0 for a bisected face and 0.5 when the line passes through a face end. A cell takes
the largest $\beta$ of its faces. A Voronoi face is bisected only when its two generators sit
at the same distance from its two ends, so the offset can be large where the angle is zero.

```{eval-rst}
.. plot:: theory/figures/mesh_face_offset.py
   :alt: The bisection offset of two Voronoi cells and of two triangles.
   :caption: Left: two Voronoi cells whose generators sit 0.6 above the middle of their face
      (square). Right: the two triangles above. Both measures come from ``mesh_qa``.
```

(mesh-top)=
## 6. The top of a cell

The top of a cell is one number read from the DEM $Z$ by the rule that
{toml}`modflow6.sgrid.top_sampling.mode` picks, `centroid` by default. The bottom always takes
the centroid rule.

### Centroid

The code interpolates the DEM at the cell centre between the four pixel centres around it,
with a zero weight on a nodata pixel:

$$
\tilde z_c = \frac{\sum_{k=1}^{4} w_k\, Z_k\, \mathbf{1}[Z_k \text{ valid}]}
{\sum_{k=1}^{4} w_k\, \mathbf{1}[Z_k \text{ valid}]} .
$$

The cell is inactive when its centre is outside the raster or the four pixels are nodata. On
an incised channel the centre often falls on a bank, so the cell is too high. On a `voronoi`
mesh, a river cell whose centre lies off the river line takes the minimum of its pixels in this
mode too. This happens where a contact crosses the river, where two thalwegs share a cell and
at a river end near the boundary.

### Zonal

The zonal rule reduces the pixels whose centre falls in the cell. A pixel is a channel pixel
when the stream raster of the delineation marks it, with the mask widened by
{toml}`modflow6.sgrid.top_sampling.channel_buffer_px` pixels. The code reads that raster only
when {toml}`modflow6.sgrid.top_sampling.channel_source` asks for it, and without it every
pixel is a hillslope pixel. With the statistic of
{toml}`modflow6.sgrid.top_sampling.channel_stat` on the channel pixels and of
{toml}`modflow6.sgrid.top_sampling.hillslope_stat` on the others, the top reads

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

Then a hillslope top more than $\varepsilon_z$ away from $\tilde z_c$ goes back to it, which
guards against a nodata edge. Channel cells are exempt, and $\varepsilon_z = 0$ switches the
guard off. A lowered top must also stay above the bottom. On the regular grid the code raises
the top to at least $z_{\mathrm{bot},c} + b_{\min}$. On a triangle or Voronoi mesh the top
stays. The bottom follows it down when the column left is thinner than $b_{\min}$ or than a
tenth of the column of the centre sample:

$$
z_{\mathrm{bot},c} \leftarrow z_{\mathrm{top},c}
- \max\bigl(\tilde z_c - z_{\mathrm{bot},c},\ b_{\min}\bigr).
$$

The cell then keeps the thickness of its centre sample, because MODFLOW 6 cannot solve under
Newton a column of a few decimetres next to neighbours of tens of metres. Elsewhere the bottom
stays, so a lowered top thins every layer of the column. The log counts these changes once per
build.

```{eval-rst}
.. plot:: theory/figures/mesh_zonal_top.py
   :alt: A cell over an incised channel and its three candidate tops.
   :caption: A cell of 32 m radius over 5 m pixels, its centre on a bank 18 m from a channel
      incised 2 m (blue). The centroid sample and the hillslope median sit about 4 m above
      the channel minimum of ``zonal_top``.
```

The zonal rule falls back to the centroid value, with a message in the log, in three cases. The
surface has no georeferencing, the channel source has no stream raster, or the cells of a
structured grid cover fewer than two DEM pixels.

(mesh-layers)=
## 7. Thickness and layers

One table, `[domain.layers]`, cuts each column into layers for MODFLOW 6 and MODFLOW-NWT
alike, and the code moves the older `[modflow6.sgrid.vertical]` or
`[modflownwt.sgrid.vertical]` to it. With {toml}`domain.layers.genmtd_lay` at `constant`,
`decay` or `list`, the layers are the same shares of the thickness in every cell
({eq}`eq-layer-bottom`, {ref}`gwf-layers`). Every layer shares the cells of the plan. A cell is
inactive in every layer when its top or its bottom is nodata, not finite, or at or below the
nodata value.

(mesh-layer-surfaces)=
### Layers by surfaces

With `genmtd_lay = "surfaces"`, each `[[domain.layers.layer]]` table gives the base of its
layer with one key: a `thickness` below the layer above (below the terrain for the first
layer), a `depth` below the terrain, an `elevation`, or a `surface`, the name of a raster of
`[[data.layer_base.sources]]`. The last layer ends on the base of the aquifer of
`[domain.depth_model]` ({ref}`gwf-domain`). A raster that leaves a cell without a value is
refused. Each base stays between the base of the aquifer and the base of the layer above, so
bases never cross. Where a layer is thinner than its `min_thickness`, the code pinches it out
as {toml}`domain.layers.pinch_out` says:

| `pinch_out` | What the cell becomes |
|---|---|
| `pass_through` | a vertical pass-through cell, `idomain = -1`. Its thickness goes to the active cell below it, or above it at the base of the column, so the column keeps its top, its base and its transmissivity |
| `keep_min_thickness` | a cell of the minimum thickness. Its base moves down, and so do the bases of the layers below it and the base of the aquifer |

```{eval-rst}
.. plot:: theory/figures/mesh_pinch_out.py
   :alt: Three layers by surfaces with the two pinch-out rules.
   :caption: The base of the middle layer comes from a raster (dotted) that rises to the layer
      above, with a ``min_thickness`` of 4 m. Left: the thin cells pass their thickness to the
      layer below. Right: they keep 4 m and the base below them moves down.
```

With `pass_through`, a column whose layers are all too thin keeps its thickest layer active.
`idomain` is 1 for an active cell, 0 for an inactive one and -1 for a pass-through cell.
MODFLOW 6 connects the cells above and below a pass-through cell. MODFLOW-NWT has no such
cell, so it refuses `pass_through` in the file and in the grid. The build refuses an active
cell whose top is at or below its bottom. The code stores the layering with
`vertical_layout = "surfaces"` on `mesh/` ({doc}`../contribute/architecture/storage-layout`).

(mesh-top-active)=
### The top active layer

With pass-through cells, the first layer is not always the top of the column. One function
gives the top active layer of each column. A point, a well or an observation without a layer
goes to that cell. The drains, the imposed heads, the evapotranspiration surface, the
computational top, the filling of closed depressions and the saturated thickness of a
calibration read the same cell ({doc}`solvers`).

(mesh-budget)=
## 8. How many cells a size costs

The cost of a run grows with the number of cells, so this section compares a grid and a mesh
at equal cell count. Over an area $A_\Omega$, a grid of pixel side $\Delta$ has
$N_S = A_\Omega/\Delta^2$ cells. An equilateral triangle of side $\ell$ has the area
$\frac{\sqrt3}{4}\ell^2$, and a Voronoi hexagon has $\frac{\sqrt3}{2}\ell^2$ when neighbouring
seeds are $\ell$ apart, so

$$
N_T = \frac{4}{\sqrt3}\,\frac{A_\Omega}{\ell^2} \approx 2.31\,\frac{A_\Omega}{\ell^2},
\qquad
N_V = \frac{2}{\sqrt3}\,\frac{A_\Omega}{\ell^2} \approx 1.15\,\frac{A_\Omega}{\ell^2}.
$$ (eq-cell-count)

With a size field, $A_\Omega/\ell^2$ becomes $\int_\Omega \ell(\mathbf{x})^{-2}\,\mathrm{d}A$.
At the cost of the grid, Voronoi generators are $\Delta \sqrt{2/\sqrt3} \approx 1.07\,\Delta$
apart and triangles have a side of $\Delta \sqrt{4/\sqrt3} \approx 1.52\,\Delta$. For the
`voronoi` engine, {toml}`mesh.cell_size` is the square root of the cell area, so a size equal
to the pixel gives the cell count of the grid. For the `triangle` engine it is the side Gmsh
aims at, so the same size gives about 2.3 times the count. Gmsh makes 2.6 to 2.7 times on a
uniform field.

Example 04 declares no `[mesh]` section. The header of `step1_minimal.toml` counts 21406 cells
of 75 m, about $120\ \mathrm{km^2}$, and does not say if the inactive cells are in. The same
count means Voronoi generators about 81 m apart, a {toml}`mesh.cell_size` of 75 m, or
triangles of about 114 m. A real mesh refines near the interfaces, so the count of a run is the
$\mathrm{ncpl}$ of its DISV file. Also, $N_S$ counts the whole raster box, while a mesh lies in
$\Omega$.

```{eval-rst}
.. plot:: theory/figures/mesh_cell_count.py
   :alt: Number of cells against cell size for the three layouts.
   :caption: :eq:`eq-cell-count` for :math:`A_\Omega` = 120 km². Each dot holds 21406 cells.
```

(mesh-acceptance)=
## 9. The checks the code applies

The code refuses a mesh when its inputs are wrong, and it stops a run when the grid it solves
is not the stored mesh. Apart from the `voronoi` build, it refuses no mesh for its shape. The
table lists the checks that the sections above do not give.

| What is checked | Rule | What happens |
|---|---|---|
| Solver and mesh | the solver reads the engine of `[mesh]` | refused when the file is read: `reads the meshes of the engines` |
| River size | {toml}`mesh.river_cell_size` at most {toml}`mesh.cell_size` | refused when the file is read |
| Voronoi build | each cell covers its generator, conformal faces lie on their lines, river chains are connected, the areas add up to the domain, no repeated vertex, no face under a micrometre | the build stops with `MeshGenerationError` |
| Solved grid | the DISV or DIS grid of the solver is the stored mesh | the run stops with `IncompatibleMeshError` |
| Top and bottom | one valid cell at least, and the bottom strictly below the top on every valid cell | refused: `No finite overlapping valid cells found between top and bottom surfaces.` or `Bottom surface must be strictly below top surface on valid cells` |
| Thick cells | thickness above the larger of 10 times the median and 500 m | warning on triangle and Voronoi meshes: `Aquifer thickness outliers:` |
| Cell shape | no triangle corner under 20 degrees, no face crossed more than 0.25 of its length from its middle, no concave cell | warning at build |
| Imported triangulation | no vertex inside an edge that does not hold it, no two vertices closer than 1e-9 of the extent | a T-junction is refused with its coordinates, duplicates warn |
| Active cells | one group joined by faces and vertical connections | warning with the number and sizes of the groups |
| Point on the mesh | a point outside the mesh lies within one cell size (the square root of the area) of a cell | no cell for the point, and a warning that names it, on every solver |

Eight fields measure the cells one by one, computed on read: `mesh_cell_area`,
`mesh_neighbour_ratio` (size ratio between neighbours), `mesh_center_offset` (offset of a
centre from its cell centroid), `mesh_nonorthogonality`, `mesh_bisection_offset`,
`mesh_min_angle`, `mesh_max_angle` and `mesh_concavity`, how far the largest angle exceeds
180°. A corner within 0.1° of 180° counts as straight. The layer `mesh_cells` of `hmp export`
carries the eight, and it names the two angle columns `min_angle_deg` and `max_angle_deg`. The
quality report `MeshQA` is stored as the attribute `qa` of `mesh/`. It holds their quantiles,
the number of concave cells and, for each line family, how much of the line the faces follow. A
mesh with a poor report still runs.

## Assumptions

- A cell has one top and one bottom, so the surface inside the cell is flat.
- A mesh is fixed for the run. It does not move with the water table.
- The conductivity is isotropic in the plane unless the flow sets `K22` or the angles of the
  tensor, which MODFLOW 6 alone reads ({ref}`gwf-tensor`).
- The coordinates are in a projected CRS in metres. The size field, the 1 mm merge of the
  Voronoi vertices and every distance of the engines rely on it.
- The zonal rule takes the channel pixels from the stream raster of the delineation. It does
  not read the observed network.

(mesh-limits)=
## Limits

- Boussinesq cannot run on Voronoi cells, nor MODFLOW-NWT on a refined mesh. The zonal top of
  MODFLOW-NWT needs {toml}`modflownwt.sgrid.top_sampling.channel_source` at `"none"`.
- Deleting `.hmp/mesh_cache/` changes the mesh of a resumed triangle run, because Gmsh gives
  another cell count, and `restart_from` refuses a run solved on another mesh.
- One request and one seed give one Voronoi mesh on one machine, GEOS and scipy build. Another
  build can give the same quality with another connectivity.
- Where the size field grows at its largest slope, a Voronoi centre sits off its cell
  centroid by about a quarter of the slope times the cell size.
- A lake arm narrower than the local cell cannot hold a pair of generators. The faces then
  follow part of the shore, and the cells of the lake are those its polygon overlaps.
- A head imposed on a side applies at the centres of the cells with a face on it: half a cell
  from the side on a regular grid, a third of the height on triangles, on the side for Voronoi
  cells.
- The tenth of the column that moves a bottom under a lowered top is empirical. It keeps the
  cells next to a quarry solvable.
- The layers are an extrusion of the plan, so the footprint and the size of the cells never
  change with depth.
- Two face lines that meet at less than 53 degrees make a gap that closes at the corner, so the
  cells at its tip take the size of the DEM pixel. Lines closer than a tenth of a pixel count
  as one.
- A nodata value read as an elevation gives a cell kilometres deep with a clean top, and the
  run converges. The thickness warning is the only sign, and a structured grid does not emit
  it.

## Parameters of this page

The keys that choose the engine, the size and the top. The keys of the layers are in
{doc}`[domain] <../reference/parameters/domain>`, those of the top in
{doc}`[modflow6] <../reference/parameters/modflow6>` and those of the mesh in
{doc}`[mesh] <../reference/parameters/mesh>`. The cards show the defaults and the allowed
values, and the developer keys are behind the developer button.

```{hmp-params}
mesh.engine
mesh.cell_size
mesh.river_cell_size
mesh.river_band
mesh.max_slope
mesh.gap_cells
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
domain.layers.genmtd_lay
domain.layers.nlay
domain.layers.lay_decay
domain.layers.lay_proportions
domain.layers.pinch_out
domain.layers.layer.thickness
domain.layers.layer.min_thickness
modflow6.runtime.mf6_enable_xt3d
```

## Checked by

The tests that import the code of this page. The box is generated, so a new test appears here
on the next build.

```{hmp-tested-by}
hydromodpy.spatial.mesh.engines
hydromodpy.spatial.mesh.sizing
hydromodpy.spatial.mesh.planning
hydromodpy.spatial.mesh.ops.voronoi
hydromodpy.spatial.mesh.ops.zonal_stats
hydromodpy.spatial.mesh.ops.mesh_orthogonality
hydromodpy.spatial.mesh.structured_grid.sgrid_generation
hydromodpy.spatial.domain.layering
hydromodpy.core.vertical_column
hydromodpy.solver.modflow_grid.discretization_spatial
hydromodpy.solver.modflow6.builders.solver_options
```

## In the code

| What | Where |
|---|---|
| The surfaces, the plan, the top, the layers | `hydromodpy/solver/modflow_grid/discretization_spatial.py` (`build_spatial_discretization`, `resolve_domain_surfaces`), `hydromodpy/spatial/domain/layering.py` (`layer_proportions`, `layer_stack`, `pinch_out`) |
| The keys of the layers, the base rasters | `hydromodpy/spatial/domain/layers_config.py`, `hydromodpy/data/variables/layer_base/`, `hydromodpy/spatial/domain/build.py` (`read_layer_base_sources`) |
| The top active layer of a column | `hydromodpy/core/vertical_column.py` (`top_active_layer`), `hydromodpy/solver/modflow_grid/solver_mesh.py` (`SolverMesh.top_active_layer`) |
| The keys of the top | `hydromodpy/spatial/mesh/structured_grid/sgrid_config.py` |
| The keys of the mesh | `hydromodpy/spatial/mesh/config/mesh.py` (`MeshConfig`) |
| The engines and their registry | `hydromodpy/spatial/mesh/engines/` (`regular`, `triangle`, `voronoi`), `hydromodpy/spatial/mesh/registry.py` |
| The request and the planner | `hydromodpy/spatial/mesh/request.py`, `hydromodpy/spatial/mesh/planning/plan.py` (`plan_mesh_request`) |
| The cleaning of the lines | `hydromodpy/spatial/mesh/planning/cleanup.py` (`clean_lines`, `drop_small_holes`) |
| The size field and the gap term | `hydromodpy/spatial/mesh/sizing/size_field.py` (`build_size_field`), `hydromodpy/spatial/mesh/sizing/gap.py` (`gap_terms`) |
| The centroid sample | `hydromodpy/spatial/surface_sampling.py` (`PreparedSurfaceSampler.sample`) |
| The zonal top | `hydromodpy/spatial/mesh/ops/zonal_stats.py` (`zonal_top`), `discretization_spatial.py` (`_zonal_top_flat`, `_zonal_structured_top`, `_bottom_under_lowered_top`, `_cells_cover_pixels`) |
| The channel mask | `hydromodpy/solver/modflow6/build.py` (`_resolve_channel_mask_for_zonal`) |
| The Voronoi tessellation | `hydromodpy/spatial/mesh/engines/voronoi/tessellation.py`, `hydromodpy/spatial/mesh/ops/voronoi.py` (`voronoi_planar_mesh`) |
| The angle of a connection | `hydromodpy/spatial/mesh/ops/mesh_orthogonality.py` (`connection_nonorthogonality_deg`, `nonorthogonality_summary`, callable on any planar `HydroMesh`) |
| The XT3D decision | `hydromodpy/solver/modflow6/builders/solver_options.py` (`resolve_xt3d_decision`) |
| The mesh step and its cache | `hydromodpy/workflow/steps/mesh.py` (`step_mesh`), `hydromodpy/spatial/mesh/cache.py` |
| The DISV export | `hydromodpy/spatial/mesh/adapters/flopy_adapter.py` (`to_flopy_disv_args`), `hydromodpy/solver/modflow6/build.py` |
| The quality report and its thresholds | `hydromodpy/spatial/mesh/model/mesh_qa.py` (`compute_mesh_qa`, `quality_warnings`, `MIN_ANGLE_WARNING_DEG`, `BISECTION_OFFSET_WARNING`, `STRAIGHT_CORNER_DEG`) |
| The checks of the table of {ref}`mesh-acceptance` | `accepted_meshes` of the flow adapters, `plan_layout` in `engines/regular/grid.py`, `engines/voronoi/gates.py`, `assert_bottom_below_top` in `layering.py`, `_warn_on_outlier_thickness` in `discretization_spatial.py`, `SolverMesh.check_interfaces`, the extractors of the solvers |
| The checks of an imported triangulation, of the active cells and of a located point | `hydromodpy/spatial/mesh/planning/input_mesh.py` (`check_triangulation`), `hydromodpy/solver/modflow_grid/active_connectivity.py` (`warn_on_disconnected_active_cells`), `hydromodpy/spatial/mesh/ops/cell_location.py` (`locate_cells_near`) |

## See also

- {doc}`solvers`: what the solvers do with the cells.
- {doc}`solvers/xt3d-on-irregular-disv-meshes`: the XT3D terms and their trigger.
- {doc}`groundwater-flow`: the equation the cells discretise.
- {doc}`../reference/parameters/mesh`: the mesh section as a reference page.
- {doc}`../contribute/architecture/mesh/mesh-engines`: the port, the planner and the three engines.

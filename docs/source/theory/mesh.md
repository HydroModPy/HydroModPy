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
   ({ref}`mesh-voronoi`). The planner first cleans the lines the mesh follows
   ({ref}`mesh-cleanup`). The two engines that grade their cells follow one size field
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
## 2. The lines and the size field of the graded engines

(mesh-cleanup)=
### Cleaning the lines

Rivers, lake shores and geology contacts come from different sources, so they miss each other
by a few metres, repeat a vertex every metre or carry holes of one square metre. The planner
cleans them before it computes any size, for every engine but a triangulation read from a
file. The tolerance is a tenth of the DEM pixel. Only the domain and the families that
{toml}`mesh.families` asks for are cleaned, with four kinds of change:

- a hole of the domain, of a lake or of the catchment whose area is below the square of the
  local cell size is dropped (an island of a lake is a hole of its polygon);
- the vertices of a line or a ring closer than the tolerance to the previous one are merged.
  The ends of an open line stay, and so does a vertex that another geometry holds at the same
  place, so a barrier laid on a shore stays on it;
- the end of a river or of a contact that runs along another line for more than twice the
  tolerance is cut back;
- the end of a river, a barrier or a contact that misses another line or a ring by less than
  the tolerance is snapped onto it, on its nearest vertex when one is that close.

A barrier is never cut back, since it carries the faces of the flow barrier and its length is
physical. What touches exactly, or lies farther than the tolerance, is left alone, so a clean
input gives the same request as before. Each kind of change is counted in one line of the log
and in one note of the mesh QA. In the code: `clean_lines`, `drop_small_holes`.

### The size field

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
the DEM pixel $\Delta$, since a cell finer than the DEM adds no information. A last term,
the gap between face lines, is defined below. The background
$\ell_b$ is $\ell_g$ inside the catchment and grows to $\kappa\,\ell_g$ outside it, with
$\kappa$ = {toml}`mesh.outside_factor`, over at least {toml}`mesh.transition_distance`, so the cells
far from the catchment are coarse.

Every term grows at most at $\sigma_{\max}$ = {toml}`mesh.max_slope` per metre, and so does their
minimum. Two neighbouring cells, about one cell apart, then differ in size by a ratio of at most
about $(1 + \sigma_{\max}/2)/(1 - \sigma_{\max}/2)$, which is 1.67 for the default 0.5. A smaller
slope gives a smoother mesh and more cells. The `regular` engine ignores the field, and so does
a triangulation read from a file.

(mesh-gap)=
### The gap between face lines

A cell larger than the space between two lines it has to follow cannot follow both. The
lines of the face families (lake shores, barriers, geology contacts, the catchment boundary)
and the outline of the domain therefore give one more term. The code simplifies each line at a
quarter of the DEM pixel and samples it every half pixel. At a sample, the gap $e$ is the
distance to the nearest point of another line. The same line counts as another when the way
along it between the two points is more than twice their distance, as for the two shores of a
narrow lake arm or a corner sharper than 53 degrees. Two lines that touch count the way
through the place where they touch, so a right-angle junction is not a gap. A line that lies on
another one counts once, and a gap outside the domain is skipped. The chord of the gap is sized

$$
\ell_e = \max\bigl(e / n_e,\ \Delta\bigr),
$$ (eq-gap-size)

with $n_e$ = {toml}`mesh.gap_cells`, 2 by default and 0 to switch the term off. The size grows
away from the chord at $\sigma_{\max}$ like the other terms. The sizes are rounded down to levels
a fourth root of 2 apart and each level is one term, so the cost is one distance transform per
level and none per line. The rivers stay out, because a river is a chain of cells and not a
face. On a generated Voronoi mesh with lakes, the planner first picks the shores the faces
follow on the field without gaps, then sizes the gaps of those shores, so an arm that the
smoothing of the shore leaves out takes no cell. In the code: `gap_terms`.

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

The column of each cell is cut into layers by one table, `[domain.layers]`, that MODFLOW 6 and
MODFLOW-NWT both read, so a project has one layering whatever solver runs it. A file that writes
the older `[modflow6.sgrid.vertical]` or `[modflownwt.sgrid.vertical]` is moved to it when the
file is read. {toml}`domain.layers.genmtd_lay` picks the rule. With `constant`, `decay` or `list`
the layers are shares of the thickness, the same shares in every cell. The rule,
{eq}`eq-layer-bottom`, and its three strategies are on {ref}`gwf-layers`.

Every layer shares the cells of the plan: the mesh is a vertical extrusion. A cell is inactive in every layer when its top or its bottom is nodata,
not finite, or at or below the nodata value.

(mesh-layer-surfaces)=
### Layers by surfaces

With `genmtd_lay = "surfaces"`, each layer gives the elevation of its base and not a share. A
`[[domain.layers.layer]]` table names a layer and gives its base with one key: a `thickness`
below the base of the layer above (below the terrain for the first layer), a `depth` below the
terrain, an `elevation`, or the name of an elevation raster, `surface`, declared under
`[[data.layer_base.sources]]`. The data section says what the raster is and the layer says
where to use it. The last layer gives no base and ends on the base of the aquifer, the one
`[domain.depth_model]` gives ({ref}`gwf-domain`). The domain places every raster on the grid of the top and
refuses one that leaves a cell without a value.

A base is kept between the base of the aquifer and the base of the layer above, so two bases
never cross. A layer thinner than its `min_thickness` in a cell is pinched out there, and
{toml}`domain.layers.pinch_out` says how:

| `pinch_out` | What the cell becomes |
|---|---|
| `pass_through` | a vertical pass-through cell, `idomain = -1`. Its thickness goes to the active cell below it, or above it at the base of the column, so the column keeps its top, its base and its transmissivity |
| `keep_min_thickness` | a cell of the minimum thickness. Its base moves down, and so do the bases of the layers below it and the base of the aquifer |

`idomain` is 1 for an active cell, 0 for an inactive one and -1 for a pass-through cell, and a
cell is active when it is above 0. MODFLOW 6 connects the cell above a pass-through cell to the
one below it. MODFLOW-NWT has no such cell: the file is refused when it is read if it asks for
`pass_through` with that solver, and the build refuses a grid that holds one. The interfaces are
computed, then checked once: an active cell whose top is at or below its bottom is refused. A
layering by surfaces is stored with `vertical_layout = "surfaces"` on `mesh/`
({doc}`../contribute/architecture/storage-layout`). A voxel model, whose surfaces are flat at a
fixed elevation, would be a value of the same table. It is not built.

(mesh-top-active)=
**The top active layer.** With pass-through cells, the first layer is not always the top of the
column. One function gives the top active layer of each column, and a point, a well or an
observation without a layer goes to that cell. The drains, the imposed heads, the surface of the
evapotranspiration, the computational top, the filling of closed depressions and the
saturated thickness of a calibration read the same cell. What each package does with it is on
{doc}`solvers`. In the code: `top_active_layer`.

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
the mesh that was stored. The code refuses no mesh for its shape, with the exception of the
build of the `voronoi` engine. The table lists what it does check. Where a limit is a number,
the table names the constant that holds it.

| What is checked | Rule | What happens | Where |
|---|---|---|---|
| Solver and mesh | the solver reads the engine of `[mesh]` | refused when the file is read: `reads the meshes of the engines` | `accepted_meshes` of the flow adapters, checked by `HydroModPyConfig` |
| Size of the regular grid | not finer than the DEM pixel | refused when the mesh is built: `the regular engine cannot mesh finer than the DEM` | `plan_layout` in `engines/regular/grid.py` |
| Size of the rivers | {toml}`mesh.river_cell_size` at most {toml}`mesh.cell_size` | refused when the file is read | `MeshConfig` in `spatial/mesh/config/mesh.py` |
| Voronoi build | every cell covers its generator, the conformal faces lie on their lines, each river chain is connected, the areas add up to the domain, no repeated vertex, no face under a micrometre | the build stops with `MeshGenerationError`, never a warning | `engines/voronoi/gates.py` |
| Solved grid | the DISV or DIS grid of the solver is the stored mesh | the run stops with `IncompatibleMeshError` | the extractors of the solvers |
| Top and bottom overlap | at least one cell where both are valid | refused: `No finite overlapping valid cells found between top and bottom surfaces.` | `assert_bottom_below_top` in `layering.py` |
| Bottom below top | strictly, on every valid cell | refused: `Bottom surface must be strictly below top surface on valid cells` | the same function |
| Cells much thicker than the rest | thickness above the larger of 10 times the median and 500 m | warning only, triangle and Voronoi meshes only: `Aquifer thickness outliers:` | `_warn_on_outlier_thickness`; constants `_THICKNESS_OUTLIER_FACTOR` and `_THICKNESS_OUTLIER_FLOOR_M` in `discretization_spatial.py` |
| Cell shape | no triangle with a corner under 20 degrees, no face crossed beyond 0.25 of its length from its middle, no concave cell | warning at build, counted in the log | `quality_warnings` in `mesh_qa.py`; constants `MIN_ANGLE_WARNING_DEG`, `BISECTION_OFFSET_WARNING` |
| Imported triangulation | no vertex lying inside the edge of a triangle that does not hold it, and no two vertices closer than 1e-9 of the extent | a T-junction is refused with its coordinates, duplicates are a warning | `check_triangulation` in `planning/input_mesh.py` |
| Active cells | one group of cells that faces and vertical connections join | warning with the number and the sizes of the groups, never a refusal | `warn_on_disconnected_active_cells` in `solver/modflow_grid/active_connectivity.py` |
| Layer interfaces | an active cell has its top above its bottom, a pass-through cell may have no thickness | refused when the grid is built | `SolverMesh.check_interfaces` |
| Point on the mesh | a point outside the mesh is within one cell size (the square root of the cell area) of a cell | no cell for the point and a warning that names it, on every solver | `locate_cells_near` in `spatial/mesh/ops/cell_location.py` |
| Non-orthogonality | the trigger of {doc}`solvers/xt3d-on-irregular-disv-meshes` | XT3D switched on, not a refusal | `resolve_xt3d_decision` |
| Zonal top | $n_{\min}$, $\varepsilon_z$, $b_{\min}$ and a tenth of the column | fallback, clamp or bottom moved, counted in the log | `zonal_top` in `zonal_stats.py`, `_bottom_under_lowered_top` in `discretization_spatial.py`; the keys are on the cards below |
| Structured grid for the zonal top | each cell covers at least two DEM pixels | zonal top skipped, resampled top kept | `_cells_cover_pixels` (argument `min_pixels`) |

The quality report of a mesh, `MeshQA`, is stored with it (the attribute `qa` of `mesh/`). It
holds the areas, the size ratio between neighbours, the offset of a centre from the centroid of
its cell, the non-orthogonality, the shape of the cells (the quantiles of the bisection offset,
of the smallest and of the largest corner, and the number of concave cells) and, for each line
family, how much of the line the faces follow. Four fields give the same per cell, computed on
read: `mesh_cell_area`, `mesh_neighbour_ratio`, `mesh_center_offset` and `mesh_nonorthogonality`.
The report is not a verdict: a mesh with a poor report still runs. The build logs one warning
for each threshold a mesh crosses, and refuses nothing: triangles with a corner under
`MIN_ANGLE_WARNING_DEG` (20 degrees), cells with a face crossed farther than
`BISECTION_OFFSET_WARNING` (0.25 of its length) from its middle, and concave cells. A mesh cache
entry written before these entries existed is read as it was and gets them measured on its
stored mesh, so the frozen mesh of a project is kept.

Four more fields exist per cell only, also computed on read, and the layer `mesh_cells` of
`hmp export` carries all eight. `mesh_bisection_offset` measures the second assumption of the
two-point flux, that the line joining two centres crosses their face in its middle. On a face of
length $L$, where that line crosses the face at a distance $s$ from its first end, the offset is

$$
\beta = \frac{\lvert s - L/2 \rvert}{L},
$$ (eq-bisection-offset)

which is 0 for a bisected face and 0.5 when the line passes through a face end; a cell takes the
largest $\beta$ of its faces. A Voronoi face is orthogonal to the line of its generators, but it
is bisected only when each generator lies at the same distance from the two ends of the face.
`mesh_min_angle` is the smallest interior angle of the cell, the usual measure of a triangle.
`mesh_max_angle` is the largest one, and `mesh_concavity` is how far it exceeds 180°, 0 for a
convex cell; a corner within `STRAIGHT_CORNER_DEG` of 180° counts as straight. The layer
`mesh_cells` names the two angle columns `min_angle_deg` and `max_angle_deg`.

## Assumptions

- A cell has one top and one bottom. The surface inside the cell is flat.
- A mesh is fixed for the run. It does not move with the water table.
- The conductivity is isotropic in the plane unless the flow sets `K22` or the angles of the
  tensor, which MODFLOW 6 alone reads ({ref}`gwf-tensor`).
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
- **Not a 3D mesh.** The layers are an extrusion of the plan, with a thickness that may change
  from cell to cell and reach zero. A footprint that changes from one layer to the next, or a
  refinement in depth, is not represented.
- **A sharp corner goes down to the pixel.** Two face lines that meet at less than 53 degrees
  make a gap that closes to zero at the corner, so the cells at its tip take the size of the DEM
  pixel. Two lines closer than a tenth of a pixel count as one.
- **An outlier thickness only warns.** A nodata value read as an elevation gives a cell
  that is kilometres deep, with a clean top, and the run converges. The warning of
  {ref}`mesh-acceptance` is the only sign, and a structured grid does not emit it.

The keys of the layers are in {doc}`[domain] <../reference/parameters/domain>`, those of the top
in {doc}`[modflow6] <../reference/parameters/modflow6>` and those of the mesh in
{doc}`[mesh] <../reference/parameters/mesh>`.

## Parameters of this page

The keys that choose the engine, the size and the top. The cards show the defaults and the
allowed values. The developer keys are behind the developer button.

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

The tests that import the code of this page. The box is generated: a new test appears
here on the next build.

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
| The zonal top | `hydromodpy/spatial/mesh/ops/zonal_stats.py` (`zonal_top`), `discretization_spatial.py` (`_zonal_top_flat`, `_zonal_structured_top`, `_bottom_under_lowered_top`) |
| The channel mask | `hydromodpy/solver/modflow6/build.py` (`_resolve_channel_mask_for_zonal`) |
| The Voronoi tessellation | `hydromodpy/spatial/mesh/engines/voronoi/tessellation.py`, `hydromodpy/spatial/mesh/ops/voronoi.py` (`voronoi_planar_mesh`) |
| The angle of a connection | `hydromodpy/spatial/mesh/ops/mesh_orthogonality.py` (`connection_nonorthogonality_deg`, `nonorthogonality_summary`) |
| The XT3D decision | `hydromodpy/solver/modflow6/builders/solver_options.py` (`resolve_xt3d_decision`) |
| The mesh step and its cache | `hydromodpy/workflow/steps/mesh.py` (`step_mesh`), `hydromodpy/spatial/mesh/cache.py` |
| The DISV export | `hydromodpy/spatial/mesh/adapters/flopy_adapter.py` (`to_flopy_disv_args`), `hydromodpy/solver/modflow6/build.py` |
| The quality report of a mesh | `hydromodpy/spatial/mesh/model/mesh_qa.py` (`compute_mesh_qa`, `quality_warnings`) |
| The checks of an imported triangulation, of the active cells and of a located point | `hydromodpy/spatial/mesh/planning/input_mesh.py` (`check_triangulation`), `hydromodpy/solver/modflow_grid/active_connectivity.py`, `hydromodpy/spatial/mesh/ops/cell_location.py` (`locate_cells_near`) |

## See also

- {doc}`solvers`: what the solvers do with the cells.
- {doc}`solvers/xt3d-on-irregular-disv-meshes`: the XT3D terms and their trigger.
- {doc}`groundwater-flow`: the equation the cells discretise.
- {doc}`../reference/parameters/mesh`: the mesh section as a reference page.
- {doc}`../contribute/architecture/mesh/mesh-engines`: the port, the planner and the three engines.

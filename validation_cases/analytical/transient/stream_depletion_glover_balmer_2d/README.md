# Stream Depletion by a Well, Glover and Balmer 2D

A well pumps beside a straight stream held at a fixed head. The case checks the
share of the pumping rate the stream gives the aquifer over time, and the
drawdown between the well and the stream and behind the well.

Numerical setup:

- geometry: 800 x 1610 m, single layer, 10 m grid (80 x 161) for MODFLOW-NWT and
  MODFLOW 6, a near-equilateral Gmsh triangle mesh (5783 triangles, 3011 nodes,
  4 m at the well, 10 m all along the stream, 60 m far away) for the MODFLOW 6
  triangle and Voronoi variants and for Boussinesq,
- flow regime: transient unconfined flow, `K = 1e-4 m/s`, `Sy = 0.1`, initial
  saturated thickness 30 m,
- stream: the west side, a Dirichlet boundary held at the initial head 30 m,
- other sides: no flow, 8 times the well-to-stream distance from the well,
- forcing: one well 100 m from the stream pumping `300 m3/day` from `t = 0`,
- time: 40 periods of 12 h, each in 4 backward-Euler steps,
- simulated observable: the per-cell constant-head budget (the stream
  depletion is its sum over the stream cells) and the head.

The stream is a side Dirichlet boundary rather than the `stream` boundary. A
fully penetrating straight stream at the edge of the aquifer is exactly such a
boundary, and every solver supports it. The `stream` boundary needs a river
network on a Gmsh mesh, holds every cell along the river edges, two cells wide,
and MODFLOW-NWT does not support it.

Reference model:

- the stream is replaced by an image recharge well mirrored across it
  (Theis 1941); the drawdown is the Theis drawdown of the well minus that of its
  image, with `T = K b` and `S = Sy`,
- the stream depletion is `erfc(sqrt(S a^2 / (4 T t)))` (Glover and Balmer 1954),
- the closed form is read where the model computes: the stream line at the
  centres of the stream cells (half a cell inside the face on the grid, about
  3 m on the triangles, on the face for the Voronoi dual), the well at the centre
  of the cell that takes the pumping, each monitor point at the centre of the
  cell it reads,
- the linearized theory holds: the largest drawdown, in the well cell, is 2.8 %
  of the saturated thickness on the grid and 3.6 % on the smaller well cell of
  the mesh, and under 1.1 % at the monitor points,
- the closed sides do not matter: an image of the well pair across each of them
  moves the monitor drawdowns by at most 3e-6 m at day 20, and the same run on a
  domain 1.5 times wider and longer moves the drawdowns and the depletion by
  6e-6.

Run manually:

```bash
python -m validation_cases.analytical.transient.stream_depletion_glover_balmer_2d.run_case --solver modflow6
```

Rebuild the triangle mesh bundle:

```bash
python -m validation_cases.analytical.transient.stream_depletion_glover_balmer_2d.mesh
```

Reference used by the documentation:

- reference: Glover and Balmer (1954) stream depletion and the image-well Theis drawdown (Theis 1941), with `T = K b` and `S = Sy`, read at the stream, well and monitor cell centres

## Equations

The equations of the reference solution the comparison uses.

$$
\frac{Q_s}{Q}=\operatorname{erfc}\left(\sqrt{\frac{S a^2}{4 T t}}\right)
$$

$$
s(x,y,t)=\frac{Q}{4\pi T}\left[E_1\left(\frac{r_1^2 S}{4 T t}\right)-E_1\left(\frac{r_2^2 S}{4 T t}\right)\right]
$$

$$
T=K\,b,\qquad S=S_y
$$

`a` is the distance from the well to the stream, `r1` the distance to the well
and `r2` the distance to its image across the stream.

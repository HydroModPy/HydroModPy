# Tilted K tensor, vertical section

Steady confined flow along a layered section whose K tensor is tilted out of
the horizontal by `[flow.param.angle2]`, with `[flow.param.Kv]` (K33) ten times
smaller than K. It checks the sign convention of ANGLE2 and the whole chain of
the tensor: the HydroModPy configuration, the NPF arrays, MODFLOW 6 with XT3D
and the stored heads and flows.

Setup:

- section of 400 m in 2 m columns, one row 2 m wide, 10 m thick in five
  confined layers of 2 m, heads of 110 m on the west end and 100 m on the east
  end of every layer, no flow on the top, the bottom and the sides, no recharge,
- K11 = K22 = 1e-4 m/s, K33 = 1e-5 m/s, ANGLE2 = +20 deg (`modflow6`) and
  -20 deg (`modflow6_mirrored`), each against its own reference; HydroModPy
  writes ANGLE1 and ANGLE3 as zero,
- XT3D on by the HydroModPy rule: MODFLOW 6 reads ANGLE2 only under XT3D,
- a linear solve without damping, closed at 1e-9 m (`config_common.toml`).

Comparison:

- simulated observable: `head` of the five layers and the `constant_head`
  budget of the run store
- reference: exact uniform flow of the tilted tensor, read in a window of
  +/- 25 m around the middle of the section
- compared quantities: the direction of the head gradient in the vertical
  plane, the heads against the plane of that direction whose level and slope
  along the section are fitted, and the flows into the west end and out of the
  east end

Sign convention: MODFLOW 6 turns K11 about the K22 axis, clockwise seen from
+y, so a positive ANGLE2 turns K11 from +x toward +z and K11 rises toward the
east. With the flow running east, the exact head then rises with elevation,
by 0.29 m over the window depth. The opposite convention gives the opposite
gradient, which the mirrored variant pins from the other side.

The ends hold one head over the whole depth, which the tilted tensor does not
carry, so the head bends near them. These end effects decay over
`l = D sqrt(det K) / (pi K_zz) = 4.9 m` and lie 33 decay lengths short of the
window. Their size sets the slope along the section, which is fitted.

Not validated: ANGLE3, a tensor tilted together with ANGLE1, inclined layers
(their stair-step error is a separate study).

Direct execution:

```bash
python -m validation_cases.analytical.steady.k_tensor_tilted_section_2d.run_case --no-show
python -m validation_cases.analytical.steady.k_tensor_tilted_section_2d.run_case --solver modflow6_mirrored --no-show
```

## Equations

MODFLOW 6 turns the K11 axis by ANGLE2 = a from +x toward +z when ANGLE1 = 0
(Langevin et al., 2017, USGS TM 6-A55), so the tensor reads in the plane

$$
K_{xx}=K_{11}\cos^2 a+K_{33}\sin^2 a,\quad
K_{zz}=K_{11}\sin^2 a+K_{33}\cos^2 a,\quad
K_{xz}=\left(K_{11}-K_{33}\right)\sin a\cos a
$$

Far from the ends no water crosses the top and the bottom, so the exact head
is a plane with

$$
\frac{\partial h/\partial z}{\partial h/\partial x}=-\frac{K_{xz}}{K_{zz}},\qquad
Q=\frac{K_{11}K_{33}}{K_{zz}}\left(-\frac{\partial h}{\partial x}\right)w\,D
$$

where $Q$ is the flow along the section, $w$ its width and $D$ its thickness.
